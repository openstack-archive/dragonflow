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

import six


class stub_wrap_db_lock(object):
    def __init__(self, type):
        pass

    def __call__(self, f):
        @six.wraps(f)
        def stub_wrap_db_lock(*args, **kwargs):
            f(*args, **kwargs)
        return stub_wrap_db_lock


import mock

# mock.patch must before import mech_driver, because mech_driver will load the
# lockedobjects_db
mock.patch('dragonflow.db.neutron.lockedobjects_db.wrap_db_lock',
           stub_wrap_db_lock).start()
from dragonflow.neutron.services.qos.notification_drivers import \
    df_qos_notification_driver
from neutron.tests import base


class TestDFQosNotificationDriver(base.BaseTestCase):

    """Test case of df qos notification drvier"""

    def setUp(self):
        super(TestDFQosNotificationDriver, self).setUp()
        self.driver = df_qos_notification_driver.\
            DFQosServiceNotificationDriver()
        self.driver.nb_api = mock.Mock()
        self.qos_policy = {'id': 'fake_id',
                          'name': 'fake_qos',
                          'tenant_id': 'fake_tenant',
                          'revision_number': 1}
        fake_service_plugin = mock.Mock()
        fake_service_plugin.get_policy = mock.Mock(
            return_value=self.qos_policy)
        mock.patch('neutron.manager.NeutronManager.get_service_plugins',
                   return_value={'QOS': fake_service_plugin}).start()

    def test_create_policy(self):
        self.driver.create_policy(mock.ANY, self.qos_policy)
        self.driver.nb_api.create_qos_policy.assert_called_with(
            'fake_id', 'fake_tenant', name='fake_qos', rules=[], version=1)

    def test_update_policy(self):
        rule = {'id': 'fake_rule_id',
                'max_burst_kbps': 1000,
                'max_kbps': 100,
                'qos_policy_id': 'fake_id'}
        self.qos_policy['rules'] = [rule]
        self.qos_policy['revision_number'] = 2
        self.driver.update_policy(mock.ANY, self.qos_policy)
        self.driver.nb_api.update_qos_policy.assert_called_with(
            'fake_id', 'fake_tenant', name='fake_qos', rules=[rule], version=2)

    def test_delete_policy(self):
        self.driver.delete_policy(mock.ANY, self.qos_policy)
        self.driver.nb_api.delete_qos_policy.assert_called_with(
            'fake_id', 'fake_tenant')
