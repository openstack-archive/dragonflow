from dragonflow.db.pubsub_drivers.redis_db_pubsub_driver import RedisPublisherAgent
from dragonflow.db.pubsub_drivers.redis_db_pubsub_driver import RedisSubscriberAgent
from dragonflow.db.db_common import DbUpdate
from dragonflow.db import pub_sub_api
import mock
from neutron.tests import base as tests_base
from oslo_serialization import jsonutils


class TestRedisPubSub(tests_base.BaseTestCase):

    def setUp(self):
        super(TestRedisPubSub, self).setUp()
        self.RedisPublisherAgent = RedisPublisherAgent()
        self.RedisSubscriberAgent = RedisSubscriberAgent()

    def test_publish_success(self):
        client = mock.Mock()
        self.RedisPublisherAgent.client = client
        client.publish.return_value = 1
        update = DbUpdate("router",
                          "key",
                          "action",
                          "value",
                          topic='teststring')
        result = self.RedisPublisherAgent.send_event(update, 'teststring')
        self.assertIsNone(result)

    def test_subscribe_success(self):
        pubsub = mock.Mock()
        self.RedisSubscriberAgent.pub_sub = pubsub
        update = DbUpdate("router",
                          "key",
                          "action",
                          "value",
                          topic='teststring')
        event_json = jsonutils.dumps(update.to_dict())
        data = pub_sub_api.pack_message(event_json)
        self.RedisSubscriberAgent.pub_sub.listen.return_value = \
            [{'type': 'message', 'data': data}]
        self.RedisSubscriberAgent.pub_sub.subscribe.return_value = 1
        self.RedisSubscriberAgent.pub_sub.unsubscribe.return_value = 1
        result = self.RedisSubscriberAgent.register_topic('subscribe')
        self.assertIsNone(result)
        result = self.RedisSubscriberAgent.unregister_topic('subscribe')
        self.RedisSubscriberAgent.db_changes_callback = mock.Mock()
        self.RedisSubscriberAgent.db_changes_callback.return_value = 1
        self.assertIsNone(result)
