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
import argparse
import signal
import sys
import uuid

from jsonmodels import fields
from oslo_log import log
from oslo_service import service
from skydive.rest.client import RESTClient
from skydive.websocket import client as skydive_client

from dragonflow import conf as cfg
from dragonflow.controller import df_config
from dragonflow.controller import service as df_service
from dragonflow.db import api_nb
from dragonflow.db import model_framework as mf
from dragonflow.db import model_proxy
from dragonflow.db.models import all  # noqa

LOG = log.getLogger(__name__)

DRAGONFLOW_HOST_ID = 'dragonflow-skydive'
DF_SKYDIVE_NAMESPACE_UUID = uuid.UUID('8a527b24-f0f5-4c1f-8f3d-6de400aa0145')

global_skydive_client = None


class SkydiveClient(service.Service):
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
            LOG.error('Failed authenticating with SkyDive analyzer at %s',
                      cfg.CONF.df_skydive.analyzer_endpoint)
            return
        self.websocket_client.connect()

    @staticmethod
    def create():
        """Create a new SkydiveClient
        :return a newly allocated SkydiveClient
        :rtype SkydiveClient
        """
        from dragonflow.common import utils as df_utils
        df_utils.config_parse()
        nb_api = api_nb.NbApi.get_instance(False, True)
        return SkydiveClient(nb_api)

    def clear_dragonflow_items(self):
        """Delete all the items created by DragonFlow"""
        restclient = RESTClient(cfg.CONF.df_skydive.analyzer_endpoint)
        edges = restclient.lookup_edges("G.E().Has('source': 'dragonflow')")
        for edge in edges:
            edge_del_msg = skydive_client.WSMessage(
                "Graph",
                skydive_client.EdgeDeletedMsgType,
                edge
            )
            self.sendWSMessage(edge_del_msg)
        nodes = restclient.lookup_nodes("G.V().Has('source': 'dragonflow')")
        for node in nodes:
            node_del_msg = skydive_client.WSMessage(
                "Graph",
                skydive_client.NodeDeletedMsgType,
                node
            )
            self.sendWSMessage(node_del_msg)

    def start(self):
        """Start communication with the SkyDive analyzer

        This starts the operaiton of periodically querying the nb_api and
        sending all the objects to the SkyDive analyzer.
        """
        super(SkydiveClient, self).start()
        self.websocket_client.start()

    def schedule_stop(self, wait_time):
        """Schedule a loop stop event
        :param wait_time: number of seconds until stop
        :type wait_time: int
        """
        loop = self.websocket_client.loop
        loop.call_later(wait_time, self.stop)

    def stop(self, graceful=False):
        """Stop the process of sending the updates to the SkyDive analyzer"""
        super(SkydiveClient, self).stop(graceful)
        if graceful:
            self.websocket_client.protocol.stop_when_complete()
        else:
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

    def _build_edge_message(self, src_type, src_id, dst_type, dst_id):
        id_str = '{}->{}'.format(src_id, dst_id)
        metadata = {
            'source': 'dragonflow',
            'source_type': src_type,
            'dest_type': dst_type,
        }
        result = {
            'ID': str(uuid.uuid5(DF_SKYDIVE_NAMESPACE_UUID, id_str)),
            'Child': "DF-{}".format(src_id),
            'Parent': "DF-{}".format(dst_id),
            'Host': 'dragonflow',
            'Metadata': metadata,
        }
        return result

    def _add_edge_message(self, edges, instance, field):
        if model_proxy.is_model_proxy(field):
            field = self.nb_api.get(field)
        if not hasattr(field, 'id'):
            return
        result = self._build_edge_message(
            type(instance).__name__, instance.id,
            type(field).__name__, field.id)
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
            multi_value = isinstance(field, fields.ListField)
            try:
                self._output_edge(edges, instance, key, multi_value)
            except AttributeError:
                pass  # ignore

    @staticmethod
    def _has_owner(instance):
        if not hasattr(instance, "device_owner"):
            return False
        return hasattr(instance, "device_id")

    @staticmethod
    def _get_instance_type(instance):
        return type(instance).__name__

    def _output_table_node(self, nodes, edges, instance):
        metadata = {
            'ID': "DF-{}".format(instance.id),
            'Type': WSClientDragonflowProtocol._get_instance_type(instance),
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
        # If we have an owner, add the edge from it to this instance
        if WSClientDragonflowProtocol._has_owner(instance):
            return
            # TODO(snapiri) Fix this code as it is not working correctly
            owner_class = mf.get_model(instance.device_owner)
            if not owner_class:
                return
            edge = self._build_edge_message(owner_class.__name__,
                                            instance.device_id,
                                            type(instance).__name__,
                                            instance.id)
            edges.append(edge)

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


def signal_handler(signal, frame):
    if global_skydive_client:
        LOG.info('Stopping SkyDive service')
        global_skydive_client.stop()


def set_signal_handler():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)


def main():
    """main method"""
    df_config.init(sys.argv)
    parser = argparse.ArgumentParser(description='SkyDive integration service')
    parser.add_argument('-t', '--runtime', type=int,
                        help='Total runtime (default 0 = infinite)')
    args = parser.parse_args()
    global global_skydive_client
    global_skydive_client = SkydiveClient.create()
    if args.runtime:
        global_skydive_client.schedule_stop(args.runtime)
        global_skydive_client.clear_dragonflow_items()
    set_signal_handler()
    global_skydive_client.start()


def service_main():
    nb_api = api_nb.NbApi.get_instance(False, True)
    server = SkydiveClient.create()
    df_service.register_service('df-skydive-service', nb_api, server)
    server.clear_dragonflow_items()
    service.launch(cfg.CONF, server).wait()


if __name__ == '__main__':
    main()
