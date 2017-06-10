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

import time

from oslo_log import log as logging
from oslo_serialization import jsonutils
import redis

from dragonflow import conf as cfg
from dragonflow.controller.common import constants
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


class RedisPublisherAgent(pub_sub_api.PublisherAgentBase):

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
            self.client.connection_pool.disconnect()
        self.client = None
        self.remote = None

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
        LOG.info("publish connection old masterlist %s",
                 self.redis_mgt.master_list)
        result = self.redis_mgt.redis_get_master_list_from_syncstring(
            redis_mgt.RedisMgt.global_sharedlist.raw)
        LOG.info("publish connection new masterlist %s",
                 self.redis_mgt.master_list)
        if result:
            self._update_client()

    def _send_event(self, data, topic):
        ttl = self.publish_retry_times
        alreadysync = False
        while ttl > 0:
            ttl -= 1
            try:
                if self.client is not None:
                    self.client.publish(topic, data)
                    break
            except Exception:
                if not alreadysync:
                    self._sync_master_list()
                    alreadysync = True
                    LOG.exception("publish error remote:%(remote)s ",
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
            LOG.warning("redis mgt is none")


class RedisSubscriberAgent(pub_sub_api.SubscriberAgentBase):

    def __init__(self):
        super(RedisSubscriberAgent, self).__init__()
        self.remote = None
        self.client = None
        self.ip = ""
        self.plugin_updates_port = ""
        self.pub_sub = None
        self.redis_mgt = None
        self.is_closed = True

    def initialize(self, callback):
        # find a subscriber server node and run daemon
        super(RedisSubscriberAgent, self).initialize(callback)
        self.redis_mgt = redis_mgt.RedisMgt.get_instance(
            cfg.CONF.df.remote_db_ip,
            cfg.CONF.df.remote_db_port)
        self._update_client()
        self.is_closed = False

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

    def close(self):
        self.redis_mgt = None
        self.pub_sub.close()
        self.pub_sub = None
        self.is_closed = True

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
            LOG.warning("redis mgt is none")

    def run(self):
        while not self.is_closed:
            time.sleep(0)
            try:
                if self.pub_sub is not None:
                    for data in self.pub_sub.listen():
                        if 'subscribe' == data['type']:
                            continue
                        elif 'unsubscribe' == data['type']:
                            continue
                        elif 'message' == data['type']:
                            # Redis managment module publishes node list
                            # on topic 'redis'.
                            # All other topics are for the user.
                            if data['channel'] == 'redis':
                                # redis ha message
                                message = pub_sub_api.unpack_message(
                                    data['data'])
                                value = jsonutils.loads(message['value'])
                                self.redis_mgt.redis_failover_callback(
                                    value)
                            else:
                                self._handle_incoming_event(data['data'])
                        else:
                            LOG.warning("receive unknown message in "
                                        "subscriber %(type)s",
                                        {'type': data['type']})

                else:
                    LOG.warning("pubsub lost connection %(ip)s:"
                                "%(port)s",
                                {'ip': self.ip,
                                 'port': self.plugin_updates_port})
                    time.sleep(1)

            except Exception as e:
                LOG.warning("subscriber listening task lost "
                            "connection "
                            "%(e)s", {'e': e})

                try:
                    connection = self.pub_sub.connection
                    connection.connect()
                    self.pub_sub.on_connect(connection)
                    # self.db_changes_callback(None, None, 'sync', None, None)
                    # notify restart
                    self.db_changes_callback(None, None,
                                             constants.CONTROLLER_DBRESTART,
                                             False, None)
                except Exception:
                    self.redis_mgt.remove_node_from_master_list(self.remote)
                    self._update_client()
                    # if pubsub not none notify restart
                    if self.remote is not None:
                        # to re-subscribe
                        self.register_hamsg_for_db()
                        self.db_changes_callback(
                            None, None, constants.CONTROLLER_DBRESTART, True,
                            None)
                    else:
                        LOG.warning("there is no more db node available")

                    LOG.exception("reconnect error %(ip)s:%(port)s",
                                  {'ip': self.ip,
                                   'port': self.plugin_updates_port})
