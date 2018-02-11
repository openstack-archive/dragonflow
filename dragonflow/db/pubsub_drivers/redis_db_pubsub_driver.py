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

import random
import time

from oslo_log import log as logging

from dragonflow.controller.common import constants
from dragonflow.db.drivers import redis_db_driver
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


class RedisClusterMixin(object):
    def __init__(self):
        super(RedisClusterMixin, self).__init__()
        self._cluster = None
        self.client = None

    def update_client(self):
        if not self._cluster:
            self._cluster = redis_db_driver.get_cluster()
        self.close()
        nodes = list(self._cluster.nodes)
        node_idx = random.randrange(len(nodes))
        node = nodes[node_idx]
        self.client = node.client


class RedisPublisherAgent(pub_sub_api.PublisherAgentBase, RedisClusterMixin):

    publish_retry_times = 5

    def initialize(self):
        # find a publisher server node
        super(RedisPublisherAgent, self).initialize()
        self.update_client()

    def close(self):
        if self.client:
            self.client.connection_pool.disconnect()
        self.client = None

    def _send_event(self, data, topic):
        ttl = self.publish_retry_times
        while ttl > 0:
            ttl -= 1
            try:
                if self.client is not None:
                    self.client.publish(topic, data)
                    break
            except Exception:
                LOG.exception("publish error on client: %s ", self.client)
                self._update_client()


class RedisSubscriberAgent(pub_sub_api.SubscriberAgentBase, RedisClusterMixin):

    def __init__(self):
        super(RedisSubscriberAgent, self).__init__()
        self.is_closed = True
        self.pub_sub = None

    def initialize(self, callback):
        # find a subscriber server node and run daemon
        super(RedisSubscriberAgent, self).initialize(callback)
        self.update_client()

    def update_client(self):
        super(RedisSubscriberAgent, self).update_client()
        self.pub_sub = self.client.pubsub()
        self.is_closed = False

    def close(self):
        if self.is_closed:
            return
        self.pub_sub.close()
        self.pub_sub = None
        self.is_closed = True

    def register_topic(self, topic):
        self.pub_sub.subscribe(topic)

    def unregister_topic(self, topic):
        self.pub_sub.unsubscribe(topic)

    def _handle_internal_redis_message(self, data):
        # XXX(oanson) This feature was removed, and it might be important
        pass

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
                            # Redis management module publishes node list
                            # on topic 'redis'.
                            # All other topics are for the user.
                            if data['channel'] == 'redis':
                                self._handle_internal_redis_message(data)
                            else:
                                self._handle_incoming_event(data['data'])
                        else:
                            LOG.warning("receive unknown message in "
                                        "subscriber %(type)s",
                                        {'type': data['type']})

                else:
                    LOG.warning("pubsub lost connection with %s:", self.client)
                    time.sleep(1)

            except Exception:
                LOG.exception("subscriber listening task lost connection")
                try:
                    connection = self.pub_sub.connection
                    connection.connect()
                    self.pub_sub.on_connect(connection)
                except Exception:
                    LOG.exception("reconnect error %s", self.client)
                    self.update_client()
                self.db_changes_callback(
                    None, None, constants.CONTROLLER_SYNC, None, None)
