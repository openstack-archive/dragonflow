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

from dragonflow.db.drivers import redis_db_driver
from dragonflow.tests import base as tests_base


class TestRedisDB(tests_base.BaseTestCase):

    def setUp(self):
        super(TestRedisDB, self).setUp()
        self.RedisDbDriver = redis_db_driver.RedisDbDriver()

    def test_set_key(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        client.execute_command.return_value = 1
        redis_mgt = mock.Mock()
        redis_mgt.get_ip_by_key.return_value = '0.0.0.0:1000'
        self.RedisDbDriver.redis_mgt = redis_mgt
        result = self.RedisDbDriver.set_key('table', 'key', 'value', 'topic')
        self.assertEqual(1, result)

        client.execute_command.return_value = None
        result = self.RedisDbDriver.set_key('table', 'key', 'value', 'topic')
        self.assertEqual(0, result)

    def test_get_method(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        self.RedisDbDriver._sync_master_list = mock.Mock()
        self.RedisDbDriver.clients[0] = client
        client.keys.return_value = 'a'
        client.mget.return_value = 'value'
        client.execute_command.return_value = 'value'
        redis_mgt = mock.Mock()
        self.RedisDbDriver.redis_mgt = redis_mgt
        redis_mgt.get_ip_by_key.return_value = '0.0.0.0:1000'

        result = self.RedisDbDriver.get_key('table', 'key')
        self.assertEqual('value', result)
        result = self.RedisDbDriver.get_key('table', 'key', 'topic')
        self.assertEqual('value', result)
        result = self.RedisDbDriver.get_all_entries('table')
        self.assertEqual(['value'], result)
        result = self.RedisDbDriver.get_all_entries('table', 'topic')
        self.assertEqual(['v', 'a', 'l', 'u', 'e'], result)

    def test_delete_key(self):
        client = mock.Mock()
        self.RedisDbDriver._get_client = mock.Mock(return_value=client)
        client.execute_command.return_value = 1
        redis_mgt = mock.Mock()
        self.RedisDbDriver.redis_mgt = redis_mgt
        redis_mgt.get_ip_by_key.return_value = '0.0.0.0:1000'
        result = self.RedisDbDriver.delete_key('table', 'key', 'topic')
        self.assertEqual(1, result)

        client.execute_command.return_value = None
        result = self.RedisDbDriver.delete_key('table', 'key', 'topic')
        self.assertEqual(0, result)

    def test_allocate_unique_key(self):
        client = mock.Mock()
        self.RedisDbDriver._update_client = mock.Mock(return_value=client)
        client.incr.return_value = 1
        result = self.RedisDbDriver.allocate_unique_key('fake_table')
        self.assertEqual(1, result)
