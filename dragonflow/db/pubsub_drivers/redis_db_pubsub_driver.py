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
import redis
import eventlet
from eventlet.green import zmq
from dragonflow._i18n import _LI
from oslo_log import log as logging
from oslo_serialization import jsonutils
from dragonflow.db.drivers.redis_db_driver import RedisDbDriver
from dragonflow.db import pub_sub_api
from dragonflow.common import utils as df_utils

LOG = logging.getLogger(__name__)

eventlet.monkey_patch()


class RedisPubSub(pub_sub_api.PubSubApi):
    def __init__(self):
        super(RedisPubSub, self).__init__()
        self.subscriber = RedisSubscriberAgent()
        self.publisher = RedisPublisherAgent()

    def get_publisher(self):
        return self.publisher

    def get_subscriber(self):
        return self.subscriber


class RedisPublisherAgent(pub_sub_api.PublisherAgentBase):

    def __init__(self):
        super(RedisPublisherAgent, self).__init__()
        self.remote = []
        self.client = None
        self.config = None

    def initialize(self, ip, is_neutron_server, publish_port=8866, **args):
        # find a publisher server node
        self.remote = RedisDbDriver.redis_mgt.pubsub_select_node()
        ip_port = self.remote.split(':')
        self.client= redis.client.StrictRedis(host=ip_port[0],port=ip_port[1])
        self.daemon = df_utils.DFDaemon()
        self.inproc_client = None

        if self.config:
            self.inproc_port = self.config.publisher_port + 1
        else:
            self.inproc_port = 8867

    def send_event(self, update, topic=None):
        if self.is_daemonize:
            if not self.inproc_client:
                context = zmq.Context()
                self.inproc_client = context.socket(zmq.PUSH)
                self.inproc_client.connect('tcp://127.0.0.1:%d' % self.inproc_port)

            if topic:
                update.topic = topic
            event_json = jsonutils.dumps(update.to_array())
            self.inproc_client.send(event_json)
            eventlet.sleep(0)

    def run(self):
        context = zmq.Context()
        inproc_server = context.socket(zmq.PULL)
        inproc_server.bind('tcp://127.0.0.1:%d' % self.inproc_port)
        eventlet.sleep(0.2)
        while True:
            event = None
            event = inproc_server.recv()
            event_json = jsonutils.loads(event)
            topic = event_json['topic']
            self.client.publish(topic, event_json)
            LOG.debug("sending %s" % event)
            eventlet.sleep(0)

class RedisSubscriberAgent(pub_sub_api.SubscriberAgentBase):
    def __init__(self):
        super(RedisSubscriberAgent, self).__init__()
        self.remote = []
        self.client = None
        self.ip = ""
        self.plugin_updates_port = ""
        self.pub_sub = None

    def initialize(self, callback, config=None, **args):
        # find a subscriber server node and run daemon
        self.remote = RedisDbDriver.redis_mgt.pubsub_select_node()
        ip_port = self.remote.split(':')
        self.client= redis.client.StrictRedis(host=ip_port[0],port=ip_port[1])
        self.ip = ip_port[0]
        self.plugin_updates_port = ip_port[1]
        self.pub_sub = self.client.pubsub()
        self.db_changes_callback = callback
        self.daemon = df_utils.DFDaemon()

    def register_topic(self, topic):
        self.pub_sub.subscribe(topic)

    def unregister_topic(self, topic):
        self.pub_sub.unsubscribe(topic)

    def run(self):
        LOG.info(_LI("Starting  Subscriber on ports %(port_1)s %(port_2)s")
                % {'port_1': self.plugin_updates_port,
                    'port_2': self.controllers_updates_port})
        while True:
            eventlet.sleep(0)
            try:
                for data in self.sub.listen():
                    if 'subscribe'==data ['type']:
                        continue
                    if 'unsubscribe'==data['type']:
                        continue
                    if 'message'==data['type']:
                        entries = jsonutils.loads(data['data'])
                        # entries = [table, key, action, value]
                        self.db_changes_callback(entries[0], entries[1], entries[2],entries[3])

            except Exception as e:
                LOG.warning(e)
                self.pub_sub.channels = {}
                try:
                    connection =self.pub_sub.connection
                    connection.connect()
                    self.db_changes_callback(None, None, 'sync',None)
                except Exception as e:
                        LOG.info(_LI("Try fix connection failed  %(ip)s %(port)s")
		                            % {'port_1': self.ip,'port_2': self.plugin_updates_port})


