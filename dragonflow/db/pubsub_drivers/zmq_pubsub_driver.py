# All Rights Reserved.
#
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

import sys

import eventlet
from eventlet.green import zmq

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from neutron.agent.common import config
from neutron.common import config as common_config

from dragonflow._i18n import _, _LI, _LE
from dragonflow.db import pub_sub_api

LOG = logging.getLogger(__name__)

eventlet.monkey_patch()

ZMQ_PUBLISHER_OPTS = [
    cfg.PortOpt(
        'publisher_port',
        default=8866,
        help=_('Neutron Server Publishers Port')
    ),
    cfg.StrOpt(
        'endpoint',
        default='*:$publisher_port',
        help=_('Neutron Server Publishers bind address')
    ),
    cfg.StrOpt(
        'ipc_socket',
        #default='/usr/local/var/run/zmq-pulisher-socket',
        default='/tmp/zmq-pulisher-socket',
        help=_('Neutron Server Publisher ZMQ inter-process socket address')
    ),
    cfg.StrOpt(
        'transport_proto',
        default='tcp',
        help=_('Neutron Server Publisher transport protocol')
    ),
]

cfg.CONF.register_opts(ZMQ_PUBLISHER_OPTS, group='zmq_publisher')


class ZMQPubSub(pub_sub_api.PubSubApi):
    def __init__(self):
        super(ZMQPubSub, self).__init__()
        self.subscriber = ZMQSubscriberAgent()
        self.publisher = ZMQPublisherAgent()

    def get_publisher(self):
        return self.publisher

    def get_subscriber(self):
        return self.subscriber


class ZMQPublisherService(object):
    def __init__(self):
        self.endpoint = cfg.CONF.zmq_publisher.endpoint
        self.ipc_socket = cfg.CONF.zmq_publisher.ipc_socket
        self.transport_proto = cfg.CONF.zmq_publisher.transport_proto

    def run(self):
        context = zmq.Context()
        inproc_server = context.socket(zmq.PULL)
        LOG.debug("about to bind to IPC socket: %s" % self.ipc_socket)
        inproc_server.bind('ipc://%s' % self.ipc_socket)
        socket = context.socket(zmq.PUB)
        if self.transport_proto == 'tcp':
            #TODO(gampel) Handle address in use exception
            socket.bind("tcp://%s" % self.endpoint)
        elif self.transport_proto == 'epgm':
            socket.connect("epgm://%s" % self.endpoint)
        else:
            LOG.error(_LE("ZMQ driver does not support trasport %s") %
                    self.trasport_proto)
            return

        while True:
            try:
                event = inproc_server.recv()
                event_json = jsonutils.loads(event)
                topic = event_json['topic'].encode('utf8')
                data = pub_sub_api.pack_message(event_json)
                socket.send_multipart([topic, data])
                LOG.debug("sending %s" % event)
            except Exception as e:
                LOG.error(_LE("Got exception %s in ZMQ publisher") % e)


class ZMQPublisherAgent(pub_sub_api.PublisherAgentBase):

    def initialize(self, **args):
        super(ZMQPublisherAgent, self).initialize(**args)
        self.inproc_client = None
        self.ipc_socket = cfg.CONF.zmq_publisher.ipc_socket

    def send_event(self, update, topic=None):
        if not self.inproc_client:
            context = zmq.Context()
            self.inproc_client = context.socket(zmq.PUSH)
            self.inproc_client.connect('ipc://%s' % self.ipc_socket)
        #NOTE(gampel) In this reference implementation we develop a trigger
        #based pub sub without sending the value mainly in order to avoid
        #consistency issues in th cost of extra latency i.e get
        update.value = None

        if topic:
            update.topic = topic
        event_json = jsonutils.dumps(update.to_array())
        self.inproc_client.send(event_json)
        LOG.debug("sending %s" % update)


class ZMQSubscriberAgent(pub_sub_api.SubscriberAgentBase):

    def __init__(self):
        super(ZMQSubscriberAgent, self).__init__()
        self.sub_socket = None

    def register_listen_address(self, uri):
        super(ZMQSubscriberAgent, self).register_listen_address(uri)
        #TODO(gampel)interrupt the sub socket recv and reconnect

    def unregister_listen_address(self, uri):
        super(ZMQSubscriberAgent, self).register_listen_address(uri)
        #TODO(gampel)interrupt the sub socket recv and reconnect

    def _connect(self):
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        for uri in self.uri_list:
            #TODO(gampel) handle exp zmq.EINVAL,zmq.EPROTONOSUPPORT
            socket.connect(uri)
        for topic in self.topic_list:
            socket.setsockopt(zmq.SUBSCRIBE, topic)
        return socket

    def register_topic(self, topic):
        super(ZMQSubscriberAgent, self).register_topic(topic)
        if self.sub_socket:
            self.sub_socket.setsockopt(zmq.SUBSCRIBE, topic)

    def unregister_topic(self, topic):
        super(ZMQSubscriberAgent, self).unregister_topic(topic)
        if self.sub_socket:
            self.sub_socket.setsockopt(zmq.UNSUBSCRIBE, topic)

    def run(self):
        self.sub_socket = self._connect()
        LOG.info(_LI("Starting  Subscriber on ports %(endpoints)s ")
                % {'endpoints': str(self.uri_list)})
        while True:
            try:
                eventlet.sleep(0)
                [topic, data] = self.sub_socket.recv_multipart()
                entry_json = pub_sub_api.unpack_message(data)
                self.db_changes_callback(
                        entry_json['table'],
                        entry_json['key'],
                        entry_json['action'],
                        entry_json['value'])
            except Exception as e:
                LOG.warning(e)
                self.sub_socket.close()
                self.sub_socket = self._connect()
                self.db_changes_callback(None, None, 'sync',
                                         None)

def main():
    common_config.init(sys.argv[1:])
    config.setup_logging()
    service = ZMQPublisherService()
    service.run()

if __name__ == "__main__":
    main()
