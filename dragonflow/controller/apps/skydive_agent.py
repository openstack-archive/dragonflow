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
    def __init__(self, nb_api):
        super(WSClientDragonflowProtocol, self).__init__()
        self.nb_api = nb_api

    def onOpen(self):
        LOG.debug('onOpen')
        df_objects = get_df_objects(self.nb_api)
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
        LOG.debug('SKYDIVE AGENT STARTED')

    def update_skydive_analyzer(self):
        update_skydive_analyzer(self.nb_api)


# FIXME (snapiri) This is here as the skydive keystone authentication is
# broken. When it will be fixed, this should be removed.
def login():
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


def update_skydive_analyzer(nb_api):
    protocol = WSClientDragonflowProtocol(nb_api)
    authtok = login()
    client = skydive_client.WSClient(
        host_id=DRAGONFLOW_HOST_ID,
        endpoint='ws://{0}/ws/publisher'.format(
            cfg.CONF.df_skydive.analyzer_endpoint),
        protocol=lambda: protocol,
        cookie='authtok={}'.format(authtok),
    )
    client.connect()
    client.start()


def add_edge_message(edges, nb_api, instance, field):
    if model_proxy.is_model_proxy(field):
        field = nb_api.get(field)
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


def output_edge(edges, nb_api, instance, field_name, multi_value):
    field = getattr(instance, field_name)
    if multi_value:
        for _field in field:
            add_edge_message(edges, nb_api, instance, _field)
    else:
        add_edge_message(edges, nb_api, instance, field)


def output_table_node_edges(edges, nb_api, instance):
    for key, field in type(instance).iterate_over_fields():
        multi_value = False
        if isinstance(field, fields.ListField):
            multi_value = True
        try:
            output_edge(edges, nb_api, instance, key, multi_value)
        except AttributeError:
            pass  # ignore
        break


def output_table_node(nodes, edges, nb_api, instance):
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
    output_table_node_edges(edges, nb_api, instance)


def output_table(nodes, edges, nb_api, table_name):
    model = mf.get_model(table_name)
    instances = nb_api.get_all(model)
    for instance in instances:
        output_table_node(nodes, edges, nb_api, instance)


def get_df_objects(nb_api):
    nodes = []
    edges = []
    for table_name in mf.iter_tables():
        output_table(nodes, edges, nb_api, table_name)
    result = {
        'Nodes': nodes,
        'Edges': edges,
    }
    return result


def main():
    import logging
    logging.basicConfig(level=logging.DEBUG)
    global LOG
    LOG = logging.getLogger(__name__)
    from dragonflow.common import utils as df_utils
    df_utils.config_parse()
    nb_api = api_nb.NbApi.get_instance(False)
    update_skydive_analyzer(nb_api)


if __name__ == '__main__':
    eventlet.monkey_patch()
    main()
