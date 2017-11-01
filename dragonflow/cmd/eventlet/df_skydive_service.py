#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import uuid

from jsonmodels import fields
from oslo_log import log
from skydive.websocket import client as skydive_client

from dragonflow import conf as cfg
from dragonflow.db import api_nb
from dragonflow.db import model_framework as mf
from dragonflow.db import model_proxy
from dragonflow.db.models import all  # noqa

# TODO(snapiri) We MUST have some way to clear current info and also be able
#  to also delete items that were removed, so the view will be accurate.

TEST_RUN_TIME = 30
LOG = log.getLogger(__name__)

DRAGONFLOW_HOST_ID = 'dragonflow-skydive'
DF_SKYDIVE_NAMESPACE_UUID = uuid.UUID('8a527b24-f0f5-4c1f-8f3d-6de400aa0145')


class SkydiveClient(object):
    """Main class that manages all the skydive operation."""
    def __init__(self, nb_api):
        protocol = WSClientDragonflowProtocol(nb_api)
        self.websocket_client = skydive_client.WSClient(
            host_id=DRAGONFLOW_HOST_ID,
            endpoint='ws://{0}/ws/publisher'.format(
                cfg.CONF.df_skydive.analyzer_endpoint),
            protocol=lambda: protocol
        )
        logged_in = self.websocket_client.login(
            cfg.CONF.df_skydive.analyzer_endpoint,
            cfg.CONF.df_skydive.user,
            cfg.CONF.df_skydive.password)
        if not logged_in:
            # TODO(snapiri) raise an exception
            return
        self.websocket_client.connect()

    def start(self):
        """Start communication with the SkyDive analyzer

        This starts the operaiton of periodically querying the nb_api and
        sending all the objects to the SkyDive analyzer.
        """
        self.websocket_client.start()

    def schedule_stop(self, wait_time):
        loop = self.websocket_client.loop
        loop.call_later(wait_time, self.stop)

    def stop(self):
        """Stop the process of sending the updates to the SkyDive analyzer"""
        self.websocket_client.stop()


class WSClientDragonflowProtocol(skydive_client.WSClientDebugProtocol):
    def __init__(self, nb_api):
        super(WSClientDragonflowProtocol, self).__init__()
        self.nb_api = nb_api

    def reschedule_send(self):
        # Schedule next update
        loop = self.factory.client.loop
        wait_time = cfg.CONF.df_skydive.update_interval
        loop.call_later(wait_time, self.send_df_updates)

    def send_df_updates(self):
        """Callback that is called when the client connects to the analyzer

        As the client is working asynchronously, this is where our work is
        actually being done.
        We now start sending the updates to skydive periodically.
        """
        # TODO(snapiri) Consider clearing all DF objects here to handle the
        #  case of objects removal
        df_objects = self._get_df_objects()
        LOG.debug('Sending to skydive: %s', df_objects)
        for node in df_objects["Nodes"]:
            node_add_msg = skydive_client.WSMessage(
                "Graph",
                skydive_client.NodeAddedMsgType,
                node
            )
            self.sendWSMessage(node_add_msg)

        for edge in df_objects["Edges"]:
            edge_add_msg = skydive_client.WSMessage(
                "Graph",
                skydive_client.EdgeAddedMsgType,
                edge
            )
            self.sendWSMessage(edge_add_msg)

        self.reschedule_send()

    def _add_edge_message(self, edges, instance, field):
        if model_proxy.is_model_proxy(field):
            field = self.nb_api.get(field)
        if not hasattr(field, 'id'):
            return
        id_str = '{}->{}'.format(instance.id, field.id)
        metadata = {
            'source': 'dragonflow',
            'source_type': type(instance).__name__,
            'dest_type': type(field).__name__,
        }
        result = {
            'ID': str(uuid.uuid5(DF_SKYDIVE_NAMESPACE_UUID, id_str)),
            'Child': "DF-{}".format(instance.id),
            'Parent': "DF-{}".format(field.id),
            'Host': 'dragonflow',
            'Metadata': metadata
        }
        edges.append(result)

    def _output_edge(self, edges, instance, field_name, multi_value):
        field = getattr(instance, field_name)
        if multi_value:
            for _field in field:
                self._add_edge_message(edges, instance, _field)
        else:
            self._add_edge_message(edges, instance, field)

    def _output_table_node_edges(self, edges, instance):
        for key, field in type(instance).iterate_over_fields():
            if key == 'id':
                continue
            multi_value = False
            if isinstance(field, fields.ListField):
                multi_value = True
            try:
                self._output_edge(edges, instance, key, multi_value)
            except AttributeError:
                pass  # ignore

    def _output_table_node(self, nodes, edges, instance):
        # TODO(snapiri) Get the owner and owner_id
        # then, add the reference from the owner to this object by calling
        # self._add_edge_message(edges, owner_obj, instance)
        metadata = {
            'ID': "DF-{}".format(instance.id),
            'Type': type(instance).__name__,
            'source': 'dragonflow',
            'data': instance.to_struct(),
            'Name': getattr(instance, 'name', None) or instance.id
        }
        result = {
            'Metadata': metadata,
            'ID': "DF-{}".format(instance.id),
            'Host': 'dragonflow'}
        nodes.append(result)
        self._output_table_node_edges(edges, instance)

    def _output_table(self, nodes, edges, table_name):
        model = mf.get_model(table_name)
        instances = self.nb_api.get_all(model)
        for instance in instances:
            self._output_table_node(nodes, edges, instance)

    def _get_df_objects(self):
        nodes = []
        edges = []
        for table_name in mf.iter_tables():
            self._output_table(nodes, edges, table_name)
        result = {
            'Nodes': nodes,
            'Edges': edges,
        }
        return result

    def onOpen(self):
        """Callback that is called when the client connects to the analyzer

        As the client is working asynchronously, this is where our work is
        actually being done.
        We now start sending the updates to skydive periodically.
        """
        LOG.debug('onOpen')
        # TODO(snapiri) have to handle a case in which we got disconnected
        # and then reconnected.
        self.reschedule_send()

    def onClose(self, wasClean, code, reason):
        """Callback that is called when the client disconnects

        Makes sure that the loop is stopped in case the connection was not
        closed by the client side.
        This is done to prevent the client from getting stuck in the loop
        when the connection is closed.

        :param wasClean: was the connection closed cleanly
        :type wasClean: bool
        :param code: error code of the current error
        :type code: integer
        :param reason: description of the error that occured
        :type reason: string
        """
        LOG.debug("Client closing %s %s %s", wasClean, code, reason)
        if not wasClean:
            self.factory.loop.stop()
        super(WSClientDragonflowProtocol, self).onClose(wasClean, code, reason)


class TestClass(object):
    """Test class to be used in the 'main' test program"""
    def __init__(self):
        from dragonflow.common import utils as df_utils
        df_utils.config_parse()
        nb_api = api_nb.NbApi.get_instance(False, True)
        self.client = SkydiveClient(nb_api)

    def start(self):
        self.client.start()

    def schedule_stop(self, wait_time):
        self.client.schedule_stop(wait_time)

    def stop(self):
        self.client.stop()


def main():
    """Test main class"""
    import logging
    logging.basicConfig(level=logging.DEBUG)
    global LOG
    LOG = logging.getLogger(__name__)
    test = TestClass()
    test.schedule_stop(TEST_RUN_TIME)
    test.start()
    LOG.info('Update complete')


if __name__ == '__main__':
    main()
