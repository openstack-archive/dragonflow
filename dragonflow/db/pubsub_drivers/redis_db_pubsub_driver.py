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
from oslo_log import log as logging
from oslo_serialization import jsonutils
import redis

from dragonflow._i18n import _LE, _LW, _LI
from dragonflow import conf as cfg
from dragonflow.db.drivers import redis_mgt
from dragonflow.db import pub_sub_api

LOG = logging.getLogger(__name__)


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

    publish_retry_times = 5

    def __init__(self):
        super(RedisPublisherAgent, self).__init__()
        self.remote = None
        self.client = None
        self.redis_mgt = None

    def initialize(self):
        # find a publisher server node
        super(RedisPublisherAgent, self).initialize()
        self.redis_mgt = redis_mgt.RedisMgt.get_instance(
            cfg.CONF.df.remote_db_ip,
            cfg.CONF.df.remote_db_port)
        self._update_client()

    def close(self):
        if self.remote:
            self.client.client_kill(self.remote)
        self.client = None

    def _update_client(self):
        if self.redis_mgt is not None:
            self.remote = self.redis_mgt.pubsub_select_node_idx()
            if self.remote is not None:
                ip_port = self.remote.split(':')
                self.client = redis.client.StrictRedis(host=ip_port[0],
                                                       port=ip_port[1])

    def process_ha(self):
        # None means that publisher connection should be updated.
        # If not None, the publisher connection is still working and is not
        # broken by DB single point failure.
        if self.remote is None:
            self._update_client()

    def _sync_master_list(self):
        LOG.info(_LI("publish connection old masterlist %s"),
                 self.redis_mgt.master_list)
        result = self.redis_mgt.redis_get_master_list_from_syncstring(
            redis_mgt.RedisMgt.global_sharedlist.raw)
        LOG.info(_LI("publish connection new masterlist %s"),
                 self.redis_mgt.master_list)
        if result:
            self._update_client()

    def send_event(self, update, topic=None):
        if topic:
            update.topic = topic
        local_topic = update.topic
        local_topic = local_topic.encode('utf8')
        data = pub_sub_api.pack_message(update.to_dict())
        ttl = self.publish_retry_times
        alreadysync = False
        while ttl > 0:
            ttl -= 1
            try:
                if self.client is not None:
                    self.client.publish(local_topic, data)
                    break
            except Exception:
                if not alreadysync:
                    self._sync_master_list()
                    alreadysync = True
                    LOG.exception(_LE("publish error remote:%(remote)s "),
                                  {'remote': self.remote})
                    continue
                self.redis_mgt.remove_node_from_master_list(self.remote)
                self._update_client()

    def set_publisher_for_failover(self, pub, callback):
        self.redis_mgt.set_publisher(pub, callback)

    def start_detect_for_failover(self):
        # only start in NB plugin
        if self.redis_mgt is not None:

            self.redis_mgt.daemonize()
        else:
            LOG.warning(_LW("redis mgt is none"))


class RedisSubscriberAgent(pub_sub_api.SubscriberAgentBase):

    def __init__(self):
        super(RedisSubscriberAgent, self).__init__()
        self.remote = None
        self.client = None
        self.ip = ""
        self.plugin_updates_port = ""
        self.pub_sub = None
        self.redis_mgt = None

    def initialize(self, callback):
        # find a subscriber server node and run daemon
        super(RedisSubscriberAgent, self).initialize(callback)
        self.redis_mgt = redis_mgt.RedisMgt.get_instance(
            cfg.CONF.df.remote_db_ip,
            cfg.CONF.df.remote_db_port)
        self._update_client()

    def process_ha(self):
        # None means that subscriber connection should be updated.
        # If not None, the subscriber connection is still working and is not
        # broken by DB single point failure.
        if self.remote is None:
            self._update_client()

    def _update_client(self):
        if self.redis_mgt is not None:
            self.remote = self.redis_mgt.pubsub_select_node_idx()
            if self.remote is not None:
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

    def set_subscriber_for_failover(self, sub, callback):
        self.redis_mgt.set_subscriber(sub, callback)

    def register_hamsg_for_db(self):
        if self.redis_mgt is not None:
            self.redis_mgt.register_ha_topic()
        else:
            LOG.warning(_LW("redis mgt is none"))

    def run(self):
        while True:
            eventlet.sleep(0)
            try:
                if self.pub_sub is not None:
                    for data in self.pub_sub.listen():
                        if 'subscribe' == data['type']:
                            continue
                        elif 'unsubscribe' == data['type']:
                            continue
                        elif 'message' == data['type']:
                            message = pub_sub_api.unpack_message(data['data'])

                            if message['table'] != 'ha':
                                self.db_changes_callback(
                                    message['table'],
                                    message['key'],
                                    message['action'],
                                    message['value'],
                                    message['topic'])
                            else:
                                # redis ha message
                                value = jsonutils.loads(message['value'])
                                self.redis_mgt.redis_failover_callback(
                                    value)
                        else:
                            LOG.warning(_LW("receive unknown message in "
                                            "subscriber %(type)s"),
                                        {'type': data['type']})

                else:
                    LOG.warning(_LW("pubsub lost connection %(ip)s:"
                                    "%(port)s"),
                                {'ip': self.ip,
                                 'port': self.plugin_updates_port})
                    eventlet.sleep(1)

            except Exception as e:
                LOG.warning(_LW("subscriber listening task lost "
                                "connection "
                                "%(e)s"), {'e': e})

                try:
                    connection = self.pub_sub.connection
                    connection.connect()
                    self.pub_sub.on_connect(connection)
                    # self.db_changes_callback(None, None, 'sync', None, None)
                    # notify restart
                    self.db_changes_callback(None, None, 'dbrestart', False,
                                             None)
                except Exception:
                    self.redis_mgt.remove_node_from_master_list(self.remote)
                    self._update_client()
                    # if pubsub not none notify restart
                    if self.remote is not None:
                        # to re-subscribe
                        self.register_hamsg_for_db()
                        self.db_changes_callback(None, None, 'dbrestart',
                                                 True, None)
                    else:
                        LOG.warning(_LW("there is no more db node "
                                        "available"))

                    LOG.exception(_LE("reconnect error %(ip)s:%(port)s"),
                                  {'ip': self.ip,
                                   'port': self.plugin_updates_port})
