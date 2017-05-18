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
from dragonflow.db.pubsub_drivers import zmq_pubsub_driver
from dragonflow.tests import base as tests_base


class TestZMQPubSub(tests_base.BaseTestCase):

    def setUp(self):
        super(TestZMQPubSub, self).setUp()
        self.ZMQPublisherAgent = zmq_pubsub_driver.ZMQPublisherAgent()
        self.ZMQSubscriberAgent = \
            zmq_pubsub_driver.ZMQSubscriberAgent()

        self.ZMQPublisherAgent.context = mock.Mock()
        self.ZMQSubscriberAgent.context = mock.Mock()

    def test_publish_success_with_topic(self):
        update = db_common.DbUpdate("router",
                                    "key",
                                    "action",
                                    "value",
                                    topic='teststring')
        with mock.patch.object(zmq_pubsub_driver.LOG, 'debug') as log_debug:
            result = self.ZMQPublisherAgent.send_event(update, 'teststring')
            log_debug.assert_called()
            self.ZMQPublisherAgent.socket.send_multipart.assert_called_once()
            self.assertIsNone(result)

    def test_publish_success_without_topic(self):
        update = db_common.DbUpdate("router",
                                    "key",
                                    "action",
                                    "value",
                                    topic=None)
        with mock.patch.object(zmq_pubsub_driver.LOG, 'debug') as log_debug:
            result = self.ZMQPublisherAgent.send_event(update, None)
            log_debug.assert_called()
            args = self.ZMQPublisherAgent.socket.send_multipart.call_args
            self.ZMQPublisherAgent.socket.send_multipart.assert_called_once()
            self.assertEqual(db_common.SEND_ALL_TOPIC.encode('utf-8'),
                             args[0][0][0])
            self.assertIsNone(result)

    def test_publisher_reconnection(self):
        update = db_common.DbUpdate("router",
                                    "key",
                                    "action",
                                    "value",
                                    topic='teststring')
        self.ZMQPublisherAgent.socket = None
        with mock.patch.object(zmq_pubsub_driver.LOG, 'debug') as log_debug:
            result = self.ZMQPublisherAgent.send_event(update, 'teststring')
            self.ZMQPublisherAgent.socket.bind.assert_called_once()
            self.ZMQPublisherAgent.socket.send_multipart.assert_called_once()
            log_debug.assert_called()
            self.assertEqual(1, log_debug.call_count)
            self.assertIsNone(result)

    def test_subscribe_success(self):
        result = self.ZMQSubscriberAgent.register_topic('teststring')
        self.assertIn(b'teststring', self.ZMQSubscriberAgent.topic_list)
        self.assertIsNone(result)
        result = self.ZMQSubscriberAgent.unregister_topic('teststring')
        self.assertNotIn(b'teststring', self.ZMQSubscriberAgent.topic_list)
        self.assertIsNone(result)
