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

    def initialize(self, multiprocessing_queue, endpoint, trasport_proto):
        super(ZMQPublisherAgent, self).initialize(
                                        multiprocessing_queue,
                                        endpoint,
                                        trasport_proto)
        context = zmq.Context()
        self.socket = context.socket(zmq.PUB)

        if self.trasport_proto == 'tcp':
            #TODO(gampel) Handle address in use exception
            self.socket.bind("tcp://%s" % self.endpoint)
        elif self.trasport_proto == 'epgm':
            self.socket.connect("epgm://%s" % self.endpoint)
        eventlet.sleep(0.2)
        self.initialized = True

    def send_event(self, update, topic=None):
        if not self.initialized:
            return
        #NOTE(gampel) In this reference implementation we develop a trigger
        #based pub sub without sending the value mainly in order to avoid
        #consistency issues in th cost of extra latency i.e get
        update.value = None
        if not topic:
            topic = update.topic
        event_json = jsonutils.dumps(update.to_array())
        data = self.pack_message(event_json)
        self.lock.acquire()
        self.socket.send_multipart([topic, data])
        LOG.debug("sending %s" % update)
        self.lock.release()
        eventlet.sleep(0)


class ZMQSubscriberAgent(pub_sub_api.SubscriberAgentBase):

    def __init__(self):
        super(ZMQSubscriberAgent, self).__init__()
        self.sub_socket = None

    def register_listen_address(self, uri):
        super(ZMQSubscriberAgent, self).register_listen_address(uri)

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
