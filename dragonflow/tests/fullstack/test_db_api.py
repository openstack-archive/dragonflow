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

import functools
import threading

from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.tests.fullstack import test_base


class TestDbApi(test_base.DFTestBase):

    def setUp(self):
        super(TestDbApi, self).setUp()
        self.driver = df_utils.load_driver(
                cfg.CONF.df.nb_db_class,
                df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        self.driver.initialize(cfg.CONF.df.remote_db_ip,
                               cfg.CONF.df.remote_db_port,
                               config=cfg.CONF.df)

    def test_simple_create_get(self):
        self.driver.create_table('test_table')
        self.addCleanup(self.driver.delete_table, 'test_table')
        self.driver.create_key('test_table', 'k1', 'v1')
        self.assertEqual('v1', self.driver.get_key('test_table', 'k1'))

    def test_get_not_found(self):
        self.driver.create_table('test_table')
        self.addCleanup(self.driver.delete_table, 'test_table')
        self.assertRaises(df_exceptions.DBKeyNotFound,
                          functools.partial(self.driver.get_key,
                                            'test_table', 'k1'))

    def test_delete_key(self):
        self.driver.create_table('test_table')
        self.addCleanup(self.driver.delete_table, 'test_table')
        self.driver.create_key('test_table', 'k1', 'v1')
        self.driver.create_key('test_table', 'k2', 'v2')
        self.driver.delete_key('test_table', 'k1')
        self.assertRaises(df_exceptions.DBKeyNotFound,
                          functools.partial(self.driver.get_key,
                                            'test_table', 'k1'))
        self.assertEqual('v2', self.driver.get_key('test_table', 'k2'))

    def test_delete_table(self):
        self.driver.create_table('test_table')
        self.driver.create_key('test_table', 'k1', 'v1')
        self.driver.delete_table('test_table')
        self.assertRaises(df_exceptions.DBKeyNotFound,
                          functools.partial(self.driver.get_key,
                                            'test_table', 'k1'))

    def test_set_key(self):
        self.driver.create_table('test_table')
        self.addCleanup(self.driver.delete_table, 'test_table')
        self.driver.create_key('test_table', 'k1', 'v1')
        self.driver.create_key('test_table', 'k2', 'v2')
        self.assertEqual('v1', self.driver.get_key('test_table', 'k1'))
        self.driver.set_key('test_table', 'k1', 'v1_2')
        self.assertEqual('v1_2', self.driver.get_key('test_table', 'k1'))
        self.assertEqual('v2', self.driver.get_key('test_table', 'k2'))

    def test_get_all_entries(self):
        self.driver.create_table('test_table')
        self.addCleanup(self.driver.delete_table, 'test_table')
        self.assertEqual([], self.driver.get_all_entries('test_table'))
        self.driver.create_key('test_table', 'k1', 'v1')
        self.driver.create_key('test_table', 'k2', 'v2')
        self.assertItemsEqual(['v1', 'v2'],
                              self.driver.get_all_entries('test_table'))

    def test_get_all_keys(self):
        self.driver.create_table('test_table')
        self.addCleanup(self.driver.delete_table, 'test_table')
        self.assertEqual([], self.driver.get_all_keys('test_table'))
        self.driver.create_key('test_table', 'k1', 'v1')
        self.driver.create_key('test_table', 'k2', 'v2')
        self.assertItemsEqual(['k1', 'k2'],
                              self.driver.get_all_keys('test_table'))

    def test_allocate_unique_key(self):
        unique_keys = [0, 0]

        def get_unique_key(idx):
            unique_keys[idx] = self.driver.allocate_unique_key('test_table')
        thread1 = threading.Thread(target=functools.partial(get_unique_key, 0))
        thread2 = threading.Thread(target=functools.partial(get_unique_key, 1))
        thread1.start()
        thread2.start()
        thread1.join(5)
        thread2.join(5)
        self.assertNotEqual(unique_keys[0], unique_keys[1])
        self.assertFalse(thread1.is_alive())
        self.assertFalse(thread2.is_alive())
