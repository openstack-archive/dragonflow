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

from dragonflow._i18n import _LE
from dragonflow.common import common_params
from dragonflow.db.drivers.redis_mgt import RedisMgt
from dragonflow.db import pub_sub_api
import eventlet
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
import redis
LOG = logging.getLogger(__name__)

eventlet.monkey_patch()

cfg.CONF.register_opts(common_params.df_opts, 'df')


class RedisPubSub(pub_sub_api.PubSubApi):

    def __init__(self):
        super(RedisPubSub, self).__init__()
        self.subscriber = RedisSubscriberAgent()
        self.publisher = RedisPublisherAgent()
        self.redis_mgt = None

    def get_publisher(self):
        return self.publisher

    def get_subscriber(self):
        return self.subscriber


class RedisPublisherAgent(pub_sub_api.PublisherApi):

    def __init__(self):
        super(RedisPublisherAgent, self).__init__()
        self.remote = None
        self.client = None
        self.redis_mgt = None

    def initialize(self):
        # find a publisher server node
        super(RedisPublisherAgent, self).initialize()
        self.redis_mgt = RedisMgt.get_instance(cfg.CONF.df.remote_db_ip,
                                              cfg.CONF.df.remote_db_port)
        self.remote = self.redis_mgt.pubsub_select_node_idx()
        ip_port = self.remote.split(':')
        self.client = redis.client.StrictRedis(host=ip_port[0],
                                               port=ip_port[1])

    def send_event(self, update, topic=None):
        if topic:
            update.topic = topic
        local_topic = update.topic
        event_json = jsonutils.dumps(update.to_dict())
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
        self.redis_mgt = None

    def initialize(self, callback):
        # find a subscriber server node and run daemon
        super(RedisSubscriberAgent, self).initialize(callback)
        self.redis_mgt = RedisMgt.get_instance(cfg.CONF.df.remote_db_ip,
                                              cfg.CONF.df.remote_db_port)
        self.remote = self.redis_mgt.pubsub_select_node_idx()
        ip_port = self.remote.split(':')
        self.client = \
            redis.client.StrictRedis(host=ip_port[0], port=ip_port[1])
        self.ip = ip_port[0]
        self.plugin_updates_port = ip_port[1]
        self.pub_sub = self.client.pubsub()

    def register_listen_address(self, uri):
        super(RedisSubscriberAgent, self).register_listen_address(uri)

    def unregister_listen_address(self, uri):
        super(RedisSubscriberAgent, self).unregister_listen_address(uri)

    def register_topic(self, topic):
        self.pub_sub.subscribe(topic)

    def unregister_topic(self, topic):
        self.pub_sub.unsubscribe(topic)

    def run(self):
        while True:
            eventlet.sleep(0)
            try:
                for data in self.pub_sub.listen():
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
                            entry_json['value'],
                            entry_json['topic'])

            except Exception as e:
                LOG.warning(e)
                try:
                    connection = self.pub_sub.connection
                    connection.connect()
                    self.db_changes_callback(None, None, 'sync', None, None)
                except Exception as e:
                    LOG.exception(_LE("reconnect error %(ip)s:%(port)s")
                                  % {'ip': self.ip,
                                     'port': self.plugin_updates_port})
