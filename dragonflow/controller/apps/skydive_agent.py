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
from oslo_serialization import jsonutils
from oslo_service import loopingcall
import requests
from skydive.websocket import client as skydive_client

from dragonflow import conf as cfg
from dragonflow.controller import df_base_app
from dragonflow.db import api_nb
from dragonflow.db import model_framework as mf

LOG = log.getLogger(__name__)

DRAGONFLOW_HOST_ID = 'dragonflow-skydive'

LOGIN_URL = 'http://{0}/login'.format(cfg.CONF.df_skydive.analyzer_endpoint)

PUBLISHER_URL = 'ws://{0}/ws/publisher'.format(
    cfg.CONF.df_skydive.analyzer_endpoint)

DF_SKYDIVE_NAMESPACE_UUID = uuid.UUID('8a527b24-f0f5-4c1f-8f3d-6de400aa0145')


class WSMessage(object):

    def __init__(self, ns, type, obj):
        self.uuid = uuid.uuid4().hex
        self.ns = ns
        self.type = type
        self.obj = obj

    def toJSON(self):
        return jsonutils.dumps(
            {
                "UUID": self.uuid,
                "Namespace": self.ns,
                "Type": self.type,
                "Obj": self.obj,
            },
        )


class WSClientDragonflowProtocol(skydive_client.WSClientDebugProtocol):
    def __init__(self, nb_api):
        super(WSClientDragonflowProtocol, self).__init__()
        self.nb_api = nb_api

    def onOpen(self):
        LOG.debug('onOpen')
        super(WSClientDragonflowProtocol, self).onOpen()
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
        LOG.debug("Client closing {was_clean} {code} {reason}".format(
            was_clean=wasClean, code=code, reason=reason))
        if not wasClean:
            self.factory.loop.stop()
        super(WSClientDragonflowProtocol, self).onClose(wasClean, code, reason)


class SkydiveAgentApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(SkydiveAgentApp, self).__init__(*args, **kwargs)
        self.pulse = loopingcall.FixedIntervalLoopingCall(
            self.update_skydive_analyzer)

        self.pulse.start(interval=10)
        LOG.debug('SKYDIVE AGENT STARTED')

    def update_skydive_analyzer(self):
        update_skydive_analyzer(self.nb_api)


# FIXME (snapiri) This is here as the skydive keystone authentication is
# broken. When it will be fixed, this should be removed.
def login():
    res = requests.post(
        LOGIN_URL,
        data={
            'username': cfg.CONF.df_skydive.user,
            'password': cfg.CONF.df_skydive.password,
        },
    )
    LOG.debug('Reply: %r', res.__dict__)
    authtok = res.cookies['authtok']
    return authtok


def update_skydive_analyzer(nb_api):
    protocol = skydive_client.WSClientDragonflowProtocol(nb_api)
    authtok = login()
    client = skydive_client.WSClient(
        host_id=DRAGONFLOW_HOST_ID,
        endpoint=PUBLISHER_URL,
        protocol=lambda: protocol,
        cookie='authtok={}'.format(authtok),
    )
    client.connect()
    client.start()


def output_edge(edges, nb_api, instance, field_name):
    field_proxy = getattr(instance, field_name)
    field = nb_api.get(field_proxy)
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


def output_table_node_edges(edges, nb_api, instance):
    for key, field in type(instance).iterate_over_fields():
        if isinstance(field, fields.ListField):
            types = field.items_types
            continue  # TODO(oanson) Not supported
        else:
            types = field.types
        for field_type in types:
            try:
                output_edge(edges, nb_api, instance, key)
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


if __name__ == '__main__':
    from dragonflow.common import utils as df_utils
    df_utils.config_parse()
    nb_api = api_nb.NbApi.get_instance(False)
    update_skydive_analyzer(nb_api)
