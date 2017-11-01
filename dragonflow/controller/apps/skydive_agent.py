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
import eventlet
import uuid

from jsonmodels import fields
from oslo_log import log
from oslo_service import loopingcall
import requests
from skydive.websocket import client as skydive_client

from dragonflow import conf as cfg
from dragonflow.controller import df_base_app
from dragonflow.db import api_nb
from dragonflow.db import model_framework as mf
from dragonflow.db import model_proxy
from dragonflow.db.models import all  # noqa

# TODO(snapiri) we MUST have some way to clear current info and also be able
#  to also delete items that were removed, so the view will be accurate.

LOG = log.getLogger(__name__)

DRAGONFLOW_HOST_ID = 'dragonflow-skydive'
DF_SKYDIVE_NAMESPACE_UUID = uuid.UUID('8a527b24-f0f5-4c1f-8f3d-6de400aa0145')


class WSClientDragonflowProtocol(skydive_client.WSClientDebugProtocol):
    def __init__(self, client):
        super(WSClientDragonflowProtocol, self).__init__()
        self.client = client

    def onOpen(self):
        LOG.debug('onOpen')
        df_objects = self.client.get_df_objects()
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

        self.stop_when_complete()

    def onClose(self, wasClean, code, reason):
        LOG.debug("Client closing %s %s %s", wasClean, code, reason)
        if not wasClean:
            self.factory.loop.stop()
        super(WSClientDragonflowProtocol, self).onClose(wasClean, code, reason)


class SkydiveAgentApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(SkydiveAgentApp, self).__init__(*args, **kwargs)
        self.pulse = loopingcall.FixedIntervalLoopingCall(
            self.update_skydive_analyzer)

        self.pulse.start(interval=cfg.CONF.df_skydive.update_interval,
                         initial_delay=cfg.CONF.df_skydive.update_interval)
        self.client = SkydiveClient(self.nb_api)
        LOG.debug('SKYDIVE AGENT STARTED')

    def update_skydive_analyzer(self):
        self.client.update_skydive_analyzer()


class SkydiveClient(object):
    def __init__(self, nb_api):
        self.nb_api = nb_api
        protocol = WSClientDragonflowProtocol(self)
        authtok = self.login()
        self.client = skydive_client.WSClient(
            host_id=DRAGONFLOW_HOST_ID,
            endpoint='ws://{0}/ws/publisher'.format(
                cfg.CONF.df_skydive.analyzer_endpoint),
            protocol=lambda: protocol,
            username=cfg.CONF.df_skydive.user,
            password=cfg.CONF.df_skydive.password,
            cookie='authtok={}'.format(authtok),
            persistent=False
        )
        self.client.connect()
        self.resend=False

    # FIXME (snapiri) This is here as the skydive keystone authentication is
    # broken. When it will be fixed, this should be removed.
    def login(self):
        res = requests.post(
            'http://{0}/login'.format(cfg.CONF.df_skydive.analyzer_endpoint),
            data={
                'username': cfg.CONF.df_skydive.user,
                'password': cfg.CONF.df_skydive.password,
            },
        )
        LOG.debug('Reply: %r', res.__dict__)
        authtok = res.cookies['authtok']
        return authtok

    def update_skydive_analyzer(self):
        if not self.resend:
            self.resend=True
        else:
            self.client.protocol().onOpen()
        self.client.start()

    def add_edge_message(self, edges,instance, field):
        id_str = '{}->{}'.format(instance.id, field.id)
        if model_proxy.is_model_proxy(field):
            field = self.nb_api.get(field)
        if not hasattr(field, 'id'):
            return
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

    def output_edge(self, edges, instance, field_name, multi_value):
        field = getattr(instance, field_name)
        if multi_value:
            for _field in field:
                self.add_edge_message(edges, instance, _field)
        else:
            self.add_edge_message(edges, instance, field)

    def output_table_node_edges(self, edges, instance):
        for key, field in type(instance).iterate_over_fields():
            if key=='id':
                continue
            multi_value = False
            if isinstance(field, fields.ListField):
                multi_value = True
            try:
                self.output_edge(edges, instance, key, multi_value)
            except AttributeError:
                pass  # ignore

    def output_table_node(self, nodes, edges, instance):
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
        self.output_table_node_edges(edges, instance)

    def output_table(self, nodes, edges, table_name):
        model = mf.get_model(table_name)
        instances = self.nb_api.get_all(model)
        for instance in instances:
            self.output_table_node(nodes, edges, instance)

    def get_df_objects(self):
        nodes = []
        edges = []
        for table_name in mf.iter_tables():
            self.output_table(nodes, edges, table_name)
        result = {
            'Nodes': nodes,
            'Edges': edges,
        }
        return result


class TestClass(object):
    def __init__(self):
        from dragonflow.common import utils as df_utils
        df_utils.config_parse()
        nb_api = api_nb.NbApi.get_instance(False)
        self.client = SkydiveClient(nb_api)

    def update_skydive_analyzer(self):
        self.client.update_skydive_analyzer()


def main():
    import logging
    import time
    import threading
    logging.basicConfig(level=logging.DEBUG)
    global LOG
    LOG = logging.getLogger(__name__)
    test = TestClass()
    thread = threading.Thread(target=test.update_skydive_analyzer)
    thread.start()
    thread.join(10)
    LOG.info('round 1 complete')
    time.sleep(3)
    thread = threading.Thread(target=test.update_skydive_analyzer)
    thread.start()
    thread.join(10)
    LOG.info('round 2 complete')


if __name__ == '__main__':
    eventlet.monkey_patch()
    main()
