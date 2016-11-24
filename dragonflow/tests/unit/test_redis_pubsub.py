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

import mock

from dragonflow.db import db_common
from dragonflow.db.pubsub_drivers import redis_db_pubsub_driver
from dragonflow.tests import base as tests_base


class TestRedisPubSub(tests_base.BaseTestCase):

    def setUp(self):
        super(TestRedisPubSub, self).setUp()
        self.RedisPublisherAgent = redis_db_pubsub_driver.RedisPublisherAgent()
        self.RedisSubscriberAgent = \
            redis_db_pubsub_driver.RedisSubscriberAgent()

    def test_publish_success(self):
        client = mock.Mock()
        self.RedisPublisherAgent.client = client
        client.publish.return_value = 1
        update = db_common.DbUpdate("router",
                                    "key",
                                    "action",
                                    "value",
                                    topic='teststring')
        result = self.RedisPublisherAgent.send_event(update, 'teststring')
        self.assertIsNone(result)

    def test_subscribe_success(self):
        pubsub = mock.Mock()
        self.RedisSubscriberAgent.pub_sub = pubsub
        self.RedisSubscriberAgent.pub_sub.subscribe.return_value = 1
        self.RedisSubscriberAgent.pub_sub.unsubscribe.return_value = 1
        result = self.RedisSubscriberAgent.register_topic('subscribe')
        self.assertIsNone(result)
        result = self.RedisSubscriberAgent.unregister_topic('subscribe')
        self.assertIsNone(result)
