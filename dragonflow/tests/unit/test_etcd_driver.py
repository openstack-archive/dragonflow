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

from dragonflow.db.drivers import etcd_db_driver
from dragonflow.tests import base as tests_base


class TestEtcdDB(tests_base.BaseTestCase):

    def test_parse_none(self):
        fake_host = []
        expected = ()
        output = etcd_db_driver._parse_hosts(fake_host)
        self.assertEqual(expected, output)

    def test_parse_empty(self):
        fake_host = [""]
        expected = ()
        output = etcd_db_driver._parse_hosts(fake_host)
        self.assertEqual(expected, output)

    def test_parse_one_host(self):
        fake_host = ['127.0.0.1:80']
        expected = (('127.0.0.1', 80),)
        output = etcd_db_driver._parse_hosts(fake_host)
        self.assertEqual(expected, output)

    def test_parse_multiple_hosts(self):
        fake_host = ['127.0.0.1:80', '192.168.0.1:8080']
        expected = (('127.0.0.1', 80), ('192.168.0.1', 8080))
        output = etcd_db_driver._parse_hosts(fake_host)
        self.assertEqual(expected, output)

    def test_parse_multiple_hosts_invalid(self):
        fake_host = ['127.0.0.1:80', '192.168.0.1']
        expected = (('127.0.0.1', 80),)
        with mock.patch.object(etcd_db_driver.LOG, 'error') as log_err:
            output = etcd_db_driver._parse_hosts(fake_host)
            self.assertEqual(expected, output)
            log_err.assert_called_once_with(
                u'The host string %s is invalid.', '192.168.0.1')
