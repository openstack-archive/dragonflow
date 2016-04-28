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

from dragonflow._i18n import _LE, _LW
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
        self._update_client()

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

    def send_event(self, update, topic=None):
        if topic:
            update.topic = topic
        local_topic = update.topic
        event_json = jsonutils.dumps(update.to_dict())
        local_topic = local_topic.encode('utf8')
        data = pub_sub_api.pack_message(event_json)
        try:
            if self.client is not None:
                self.client.publish(local_topic, data)
        except Exception as e:
            LOG.warning(e)
            self.redis_mgt.remove_node_from_master_list(self.remote)
            self._update_client()
            try:
                if self.client is not None:
                    self.client.publish(local_topic, data)
            except Exception:
                self.redis_mgt.remove_node_from_master_list(self.remote)
                self._update_client()
                LOG.exception(_LE("publish error remote:%(remote)s")
                              % {'remote': self.remote})

    def _set_publisher_to_mgt(self, pub, callback):
        self.redis_mgt.set_publisher(pub, callback)

    def _start_detect_task(self):
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
        self.redis_mgt = RedisMgt.get_instance(cfg.CONF.df.remote_db_ip,
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

    def _set_subscriber_to_mgt(self, sub, callback):
        self.redis_mgt.set_subscriber(sub, callback)

    def _register_ha(self):
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
                        if 'unsubscribe' == data['type']:
                            continue
                        if 'message' == data['type']:
                            entry = pub_sub_api.unpack_message(data['data'])
                            entry_json = jsonutils.loads(entry)

                            if entry_json['table'] != 'ha':
                                self.db_changes_callback(
                                    entry_json['table'],
                                    entry_json['key'],
                                    entry_json['action'],
                                    entry_json['value'],
                                    entry_json['topic'])
                            else:
                                # redis ha message
                                value = jsonutils.loads(entry_json['value'])
                                self.redis_mgt.redis_failover_callback(
                                    value)

                else:
                    eventlet.sleep(1)
                    LOG.warning(_LW("pubsub lost connection %(ip)s:"
                                    "%(port)s")
                                % {'ip': self.ip,
                                   'port': self.plugin_updates_port})

            except Exception as e:
                LOG.warning(e)
                try:
                    connection = self.pub_sub.connection
                    connection.connect()
                    self.pub_sub.on_connect()
                    # self.db_changes_callback(None, None, 'sync', None, None)
                    # todo notify restart
                    self.db_changes_callback(None, None, 'dbrestart', None,
                                             None)
                except Exception:
                    self.redis_mgt.remove_node_from_master_list(self.remote)
                    self._update_client()
                    # todo if pubsub not none notify restart
                    # to re-subscribe
                    self.db_changes_callback(None, None, 'dbrestart', None,
                                             None)
                    LOG.exception(_LE("reconnect error %(ip)s:%(port)s")
                                  % {'ip': self.ip,
                                     'port': self.plugin_updates_port})
