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

from dragonflow.db.drivers.redis_db_driver import RedisDbDriver
from dragonflow.db import pub_sub_api
import eventlet
from oslo_log import log as logging
from oslo_serialization import jsonutils
import redis
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
        self.remote = None
        self.client = None

    def initialize(self, endpoint, trasport_proto, **args):
        # find a publisher server node
        super(RedisPublisherAgent, self).initialize(endpoint,
                                                    trasport_proto,
                                                    **args)
        self.remote = RedisDbDriver.redis_mgt.pubsub_select_node()
        ip_port = self.remote.split(':')
        self.client = redis.client.StrictRedis(host=ip_port[0],
                                               port=ip_port[1])

    def send_event(self, update, topic=None):
        if topic:
            update.topic = topic
        local_topic = update.topic
        event_json = jsonutils.dumps(update.to_array())
        local_topic = local_topic.encode('utf8')
        data = pub_sub_api.pack_message(event_json)
        self.client.publish(local_topic, data)


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
        super(RedisSubscriberAgent, self).initialize(callback,
                                                     config=None,
                                                     **args)
        self.remote = RedisDbDriver.redis_mgt.pubsub_select_node()
        ip_port = self.remote.split(':')
        self.client = \
            redis.client.StrictRedis(host=ip_port[0], port=ip_port[1])
        self.ip = ip_port[0]
        self.plugin_updates_port = ip_port[1]
        self.pub_sub = self.client.pubsub()

    def register_topic(self, topic):
        self.pub_sub.subscribe(topic)

    def unregister_topic(self, topic):
        self.pub_sub.unsubscribe(topic)

    def run(self):
        while True:
            eventlet.sleep(0)
            try:
                for data in self.sub.listen():
                    if 'subscribe' == data['type']:
                        continue
                    if 'unsubscribe' == data['type']:
                        continue
                    if 'message' == data['type']:
                        entry = pub_sub_api.unpack_message(data['data'])
                        entry_json = jsonutils.loads(entry)
                        self.db_changes_callback(
                            entry_json['table'],
                            entry_json['key'],
                            entry_json['action'],
                            entry_json['value'])

            except Exception as e:
                LOG.warning(e)
                self.pub_sub.channels = {}
                try:
                    connection = self.pub_sub.connection
                    connection.connect()
                    self.db_changes_callback(None, None, 'sync', None)
                except Exception as e:
                    LOG.erro("fix connection failed %s ip %s port %s"
                             % e, self.ip, self.plugin_updates_port)
