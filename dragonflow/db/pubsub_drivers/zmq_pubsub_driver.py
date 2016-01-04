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

import eventlet
from eventlet.green import zmq

from dragonflow._i18n import _LI
from oslo_log import log as logging
from oslo_serialization import jsonutils

from dragonflow.db import pub_sub_api

LOG = logging.getLogger(__name__)

eventlet.monkey_patch()


class ZMQPubSub(pub_sub_api.PubSubApi):
    def __init__(self):
        super(ZMQPubSub, self).__init__()
        self.subscriber = ZMQSubscriberAgent()
        self.publisher = ZMQPublisherAgent()

    def get_publisher(self):
        return self.publisher

    def get_subscriber(self):
        return self.subscriber


class ZMQPublisherAgent(pub_sub_api.PublisherAgentBase):

    def run(self):
        context = zmq.Context()
        socket = context.socket(zmq.PUB)

        #TODO(gampel) Handle address in use exception
        socket.bind("tcp://*:%d" % self.port)
        eventlet.sleep(0.2)
        while True:
            event = None
            event = self._queue.get()
            topic = event.topic
            event_json = jsonutils.dumps(event.to_array())
            data = self.pack_message(event_json)
            socket.send_multipart([topic, data])
            LOG.debug("sending %s" % event)
            eventlet.sleep(0)


class ZMQSubscriberAgent(pub_sub_api.SubscriberAgentBase):

    def __init__(self):
        super(ZMQSubscriberAgent, self).__init__()
        self.sub_socket = None

    def _connect(self):
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.connect(
                "tcp://%s:%d" % (self.ip, self.plugin_updates_port))
        socket.connect(
                "tcp://%s:%d" % (self.ip, self.controllers_updates_port))
        for topic in self.topic_list:
            socket.setsockopt(zmq.SUBSCRIBE, topic)
        return socket

    def add_topic(self, topic):
        super(ZMQSubscriberAgent, self).add_topic(topic)
        if self.sub_socket:
            self.sub_socket.setsockopt(zmq.SUBSCRIBE, topic)

    def run(self):
        self.sub_socket = self._connect()
        LOG.info(_LI("Starting  Subscriber on ports %(port_1)s %(port_2)s")
                % {'port_1': self.plugin_updates_port,
                    'port_2': self.controllers_updates_port})
        while True:
            try:
                eventlet.sleep(0)
                [topic, data] = self.sub_socket.recv_multipart()
                entry_json = self.unpack_message(data)
                entries = jsonutils.loads(entry_json)
                # entries = [table, key, action, value]
                self.db_changes_callback(entries[0], entries[1], entries[2],
                                         entries[3])
            except Exception as e:
                LOG.warning(e)
                self.sub_socket.close()
                self.sub_socket = self._connect()
                self.db_changes_callback(None, None, 'sync',
                                         None)
