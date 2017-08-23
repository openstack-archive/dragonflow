# Copyright (c) 2015 OpenStack Foundation.
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
import redis

from dragonflow.common import exceptions
from dragonflow.db.drivers import redis_db_driver
from dragonflow.tests import base as tests_base


class TestRedisDB(tests_base.BaseTestCase):
    def setUp(self):
        super(TestRedisDB, self).setUp()
        self.RedisDbDriver = redis_db_driver.RedisDbDriver()

    def test_set_key(self):
        self.RedisDbDriver._cluster = mock.Mock()
        node = mock.Mock()
        self.RedisDbDriver._cluster.get_node.return_value = node
        self.RedisDbDriver.set_key('table', 'key', 'value', 'topic')
        node.client.execute_command.assert_called_once_with(
            ['SET', '{table.topic}key', 'value'])

    def test_get_key(self):
        self.RedisDbDriver._cluster = mock.Mock()
        node = mock.Mock()
        expected = 'value'
        node.client.execute_command.return_value = expected
        self.RedisDbDriver._cluster.get_node.return_value = node
        actual = self.RedisDbDriver.get_key('table', 'key', 'topic')
        node.client.execute_command.assert_called_once_with(
            ['GET', '{table.topic}key'])
        self.assertEqual(expected, actual)

    def test_get_non_existent_key(self):
        self.RedisDbDriver._cluster = mock.Mock()
        node = mock.Mock()
        node.client.execute_command.return_value = None
        self.RedisDbDriver._cluster.get_node.return_value = node
        self.assertRaisesRegex(
            exceptions.DBKeyNotFound,
            'key',
            self.RedisDbDriver.get_key,
            'table',
            'key',
            'topic',
        )
        node.client.execute_command.assert_called_once_with(
            ['GET', '{table.topic}key'])

    def _test_key_with_side_effect(self, node1, node2, side_effect):
        def _side_effect(*args, **kwargs):
            cluster.get_node_by_host.return_value = node2
            cluster.get_node.return_value = node2
            side_effect()

        self.RedisDbDriver._cluster = mock.Mock()
        cluster = self.RedisDbDriver._cluster
        expected = 'value'
        node1.client.execute_command.side_effect = _side_effect
        node2.client.execute_command.return_value = expected
        cluster.get_node.return_value = node1
        actual = self.RedisDbDriver.get_key('table', 'key', 'topic')
        self.assertEqual(expected, actual)

    def test_moved_key(self):
        def fail(*args, **kwargs):
            raise redis.exceptions.ResponseError('MOVED 1 1.2.3.4:7000')

        node1 = mock.Mock()
        node2 = mock.Mock()
        self._test_key_with_side_effect(node1, node2, fail)
        node1.client.execute_command.assert_called_once_with(
            ['GET', '{table.topic}key'])
        node2.client.execute_command.assert_called_once_with(
            ['GET', '{table.topic}key'])
        self.RedisDbDriver._cluster.populate_cluster.assert_called_once()

    def test_migrating_key(self):
        def fail(*args, **kwargs):
            raise redis.exceptions.ResponseError('ASK 1 1.2.3.4:7000')

        node1 = mock.Mock()
        node2 = mock.Mock()
        self._test_key_with_side_effect(node1, node2, fail)
        node1.client.execute_command.assert_called_once_with(
            ['GET', '{table.topic}key'])
        node2.client.execute_command.assert_any_call(
            'ASKING')
        node2.client.execute_command.assert_any_call(
            ['GET', '{table.topic}key'])

    def test_connection_error(self):
        def fail(*args, **kwargs):
            raise redis.exceptions.ConnectionError('Error 111')

        node1 = mock.Mock()
        node2 = mock.Mock()
        self._test_key_with_side_effect(node1, node2, fail)
        node1.client.execute_command.assert_called_with(
            ['GET', '{table.topic}key'])
        node2.client.execute_command.assert_called_with(
            ['GET', '{table.topic}key'])
        self.RedisDbDriver._cluster.populate_cluster.assert_called_once()

    def test_delete_key(self):
        self.RedisDbDriver._cluster = mock.Mock()
        node = mock.Mock()
        self.RedisDbDriver._cluster.get_node.return_value = node
        self.RedisDbDriver.delete_key('table', 'key', 'topic')
        node.client.execute_command.assert_called_once_with(
            ['DEL', '{table.topic}key'])

    def test_get_all_keys_topic(self):
        expected = [b'key1', b'key2', b'key3']
        keys_response = [b'{table.topic}' + key for key in expected]
        self.RedisDbDriver._cluster = mock.Mock()
        node = mock.Mock()
        self.RedisDbDriver._cluster.get_node.return_value = node
        node.client.scan.return_value = (0, keys_response)
        actual = self.RedisDbDriver.get_all_keys('table', 'topic')
        self.assertEqual(set(expected), set(actual))

    def test_get_all_keys_notopic(self):
        nodes_keys = (
            [b'key1', b'key2', b'key3'],
            [b'key3', b'key4', b'key5'],
        )
        expected = set()
        nodes = []
        for node_keys in nodes_keys:
            expected.update(node_keys)
            keys_response = [b'{table.topic}' + key for key in node_keys]
            node = mock.Mock()
            node.client.scan.return_value = (0, keys_response)
            nodes.append(node)

        self.RedisDbDriver._cluster = mock.Mock()
        self.RedisDbDriver._cluster.nodes = nodes
        actual = self.RedisDbDriver.get_all_keys('table')
        self.assertEqual(expected, set(actual))

    def test_allocate_unique_key(self):
        self.RedisDbDriver._cluster = mock.Mock()
        node = mock.Mock()
        expected = '1'
        node.client.execute_command.return_value = expected
        self.RedisDbDriver._cluster.get_node.return_value = node
        actual = self.RedisDbDriver.allocate_unique_key('table')
        node.client.execute_command.assert_called_once_with(
            ['INCR', '{table.}unique_key'])
        self.assertEqual(expected, actual)
