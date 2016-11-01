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
from neutron.conf.services import qos_driver_manager as driver_mgr_config
from neutron import manager
from neutron.objects.qos import rule
from neutron.plugins.ml2 import config as ml2_config

from dragonflow.tests.unit import test_mech_driver


class TestDFQosNotificationDriver(test_mech_driver.DFMechanismDriverTestCase):

    """Test case of df qos notification drvier"""

    _extension_drivers = ['qos']

    def get_additional_service_plugins(self):
        p = super(TestDFQosNotificationDriver,
                  self).get_additional_service_plugins()
        p.update({'qos_plugin_name': 'qos'})
        return p

    def setUp(self):
        ml2_config.cfg.CONF.set_override('extension_drivers',
                                        self._extension_drivers,
                                        group='ml2')
        driver_mgr_config.register_qos_plugin_opts(ml2_config.cfg.CONF)
        ml2_config.cfg.CONF.set_override('notification_drivers',
                                         ['df_notification_driver'], 'qos')
        super(TestDFQosNotificationDriver, self).setUp()
        self.plugin = (manager.NeutronManager.
                       get_service_plugins()['QOS'])
        self.driver = (
            self.plugin.notification_driver_manager.notification_drivers[0])

    def _test_create_policy(self):
        qos_policy = {'policy': {'name': "policy1", 'tenant_id': "tenant1"}}
        qos_obj = self.plugin.create_policy(self.context, qos_policy)
        self.assertGreater(qos_obj['revision_number'], 0)
        self.driver.nb_api.create_qos_policy.assert_called_with(
            mock.ANY, 'tenant1', name='policy1',
            rules=[], version=qos_obj['revision_number'])
        return qos_obj

    def test_create_policy(self):
        self._test_create_policy()

    def test_update_policy(self):
        qos_obj = self._test_create_policy()
        new_qos_obj = self.plugin.update_policy(
            self.context, qos_obj['id'], {'policy': {'name': 'policy2'}})
        self.assertGreater(new_qos_obj['revision_number'],
                           qos_obj['revision_number'])
        self.driver.nb_api.update_qos_policy.assert_called_with(
            qos_obj['id'], 'tenant1', name='policy2',
            rules=[], version=new_qos_obj['revision_number'])

    def test_create_delete_policy_rule(self):
        qos_obj = self._test_create_policy()
        qos_rule = {'max_burst_kbps': 1000,
                    'max_kbps': 100}
        qos_rule_obj = self.plugin.create_policy_rule(
            self.context, rule.QosBandwidthLimitRule,
            qos_obj['id'], {'bandwidth_limit_rule': qos_rule})
        new_qos_obj = self.plugin.get_policy(self.context, qos_obj['id'])
        self.assertGreater(new_qos_obj['revision_number'],
                           qos_obj['revision_number'])
        self.driver.nb_api.update_qos_policy.assert_called_with(
            qos_obj['id'], 'tenant1', name='policy1',
            rules=[qos_rule_obj], version=new_qos_obj['revision_number'])

        self.plugin.delete_policy_rule(self.context,
                                       rule.QosBandwidthLimitRule,
                                       qos_rule_obj['id'],
                                       qos_obj['id'])
        newer_qos_obj = self.plugin.get_policy(self.context, qos_obj['id'])
        self.assertGreater(newer_qos_obj['revision_number'],
                           new_qos_obj['revision_number'])
        self.driver.nb_api.update_qos_policy.assert_called_with(
            qos_obj['id'], 'tenant1', name='policy1',
            rules=[], version=newer_qos_obj['revision_number'])

    def test_delete_policy(self):
        qos_obj = self._test_create_policy()
        self.plugin.delete_policy(self.context, qos_obj['id'])
        self.driver.nb_api.delete_qos_policy.assert_called_with(
            qos_obj['id'], 'tenant1')
