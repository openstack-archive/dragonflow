from dragonflow.db.drivers.redis_db_driver import RedisDbDriver
from neutron.tests import base as tests_base
import mock


class TestRedisDB(tests_base.BaseTestCase):

    def setUp(self):
        super(TestRedisDB, self).setUp()
        self.RedisDbDriver = RedisDbDriver()

    def test_set_success(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver.clients[0] = client
        client.set.return_value = 1
        result = self.RedisDbDriver.set_key('table', 'key', 'value', 'topic')
        self.assertEqual(result, 1)

    def test_set_failed(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver.clients[0] = client
        client.set.return_value = 0
        client.delete.return_value = 1
        result = self.RedisDbDriver.set_key('table', 'key', 'value', 'topic')
        self.assertEqual(result, 0)

    def test_get_success(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver.clients[0] = client
        client.get.return_value = 'value'
        result = self.RedisDbDriver.get_key('table', 'key', 'topic')
        self.assertEqual(result, 'value')
        client.keys.return_value = 'a'
        result = self.RedisDbDriver.get_key('table', 'key')
        self.assertEqual(result, 'value')

    def test_get_all_entries(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver.clients[0] = client
        client.keys.return_value = 'a'
        client.mget.return_value = 'value'
        result = self.RedisDbDriver.get_key('table', 'key', 'topic')
        self.assertEqual(result, 'value')
        client.keys.return_value = 'a'
        result = self.RedisDbDriver.get_all_entries('table')
        self.assertEqual(result, ['v', 'a', 'l', 'u', 'e'])
        client.keys.return_value = 'a'
        result = self.RedisDbDriver.get_all_entries('table', 'topic')
        self.assertEqual(result, ['v', 'a', 'l', 'u', 'e'])

    def test_delete_key(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver.clients[0] = client
        client.delete.return_value = 1
        result = self.RedisDbDriver.delete_key('table', 'key', 'topic')
        self.assertEqual(result, 1)

    def test_allocate_unique_key(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver.clients[0] = client
        client.incr.return_value = 1
        result = self.RedisDbDriver.allocate_unique_key()
        self.assertEqual(result, 1)

    def test_check_connection(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver.clients[0] = client
        client.get.return_value = 1
        result = self.RedisDbDriver.check_connection(0)
        self.assertEqual(result, 1)
