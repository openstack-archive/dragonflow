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

from neutron.objects.qos import rule
from neutron.plugins.ml2 import config as ml2_config
from neutron_lib.plugins import directory
import testtools

from dragonflow.db.models import qos
from dragonflow.tests.unit import test_mech_driver


@testtools.skip("bug/1683784")
class TestDFQosNotificationDriver(test_mech_driver.DFMechanismDriverTestCase):

    """Test case of df qos notification drvier"""

    def get_additional_service_plugins(self):
        p = super(TestDFQosNotificationDriver,
                  self).get_additional_service_plugins()
        p.update({'qos_plugin_name': 'qos'})
        return p

    def setUp(self):
        self._extension_drivers.append('qos')
        ml2_config.cfg.CONF.set_override('notification_drivers',
                                         ['df_notification_driver'], 'qos')
        super(TestDFQosNotificationDriver, self).setUp()
        self.plugin = directory.get_plugin('QOS')
        self.driver = (
            self.plugin.notification_driver_manager.notification_drivers[0])

    def _test_create_policy(self):
        qos_policy = {'policy': {'name': "policy1", 'project_id': 'project1'}}
        qos_obj = self.plugin.create_policy(self.context, qos_policy)
        self.assertGreater(qos_obj['revision_number'], 0)
        self.driver.nb_api.create.assert_called_with(qos.QosPolicy(
            id=qos_obj['id'],
            topic='project1',
            name='policy1',
            rules=[],
            version=qos_obj['revision_number']))
        return qos_obj

    def test_create_policy(self):
        self._test_create_policy()

    def test_update_policy(self):
        qos_obj = self._test_create_policy()
        new_qos_obj = self.plugin.update_policy(
            self.context, qos_obj['id'], {'policy': {'name': 'policy2'}})
        self.assertGreater(new_qos_obj['revision_number'],
                           qos_obj['revision_number'])
        self.driver.nb_api.update.assert_called_with(qos.QosPolicy(
            id=qos_obj['id'],
            topic='project1',
            name='policy2',
            rules=[],
            version=new_qos_obj['revision_number']))

    def test_create_delete_policy_rule(self):
        qos_obj = self._test_create_policy()
        qos_rule = {'max_burst_kbps': 1000,
                    'max_kbps': 100}
        qos_rule_obj = self.plugin.create_policy_rule(
            self.context, rule.QosBandwidthLimitRule,
            qos_obj['id'], {'bandwidth_limit_rule': qos_rule})
        qos_rule_obj.pop('qos_policy_id', None)
        new_qos_obj = self.plugin.get_policy(self.context, qos_obj['id'])
        self.assertGreater(new_qos_obj['revision_number'],
                           qos_obj['revision_number'])
        self.driver.nb_api.update.assert_called_with(qos.QosPolicy(
            id=qos_obj['id'],
            topic='project1',
            name='policy1',
            rules=[qos_rule_obj],
            version=new_qos_obj['revision_number']))

        self.plugin.delete_policy_rule(self.context,
                                       rule.QosBandwidthLimitRule,
                                       qos_rule_obj['id'],
                                       qos_obj['id'])
        newer_qos_obj = self.plugin.get_policy(self.context, qos_obj['id'])
        self.assertGreater(newer_qos_obj['revision_number'],
                           new_qos_obj['revision_number'])
        self.driver.nb_api.update.assert_called_with(qos.QosPolicy(
            id=qos_obj['id'],
            topic='project1',
            name='policy1',
            rules=[],
            version=newer_qos_obj['revision_number']))

    def test_delete_policy(self):
        qos_obj = self._test_create_policy()
        self.plugin.delete_policy(self.context, qos_obj['id'])
        self.driver.nb_api.delete.assert_called_with(qos.QosPolicy(
            id=qos_obj['id']))

    def test_create_update_network_qos_policy(self):
        nb_api = self.driver.nb_api
        qos_obj = self._test_create_policy()
        kwargs = {'qos_policy_id': qos_obj['id']}
        with self.network(arg_list=('qos_policy_id',), **kwargs) as n:
            network_id = n['network']['id']
            self.assertTrue(nb_api.create.called)
            # nb_api.create(LogicalSwitch) will be called after
            # nb_api.create(QosPolicy), so the index here is 1.
            called_args = nb_api.create.call_args_list[1][0][0]
            self.assertEqual(qos_obj['id'], called_args.qos_policy.id)

            data = {'network': {'qos_policy_id': None}}
            req = self.new_update_request('networks', data, network_id)
            req.get_response(self.api)
            self.assertTrue(nb_api.update.called)
            called_args = nb_api.update.call_args_list[0][0][0]
            self.assertIsNone(called_args.qos_policy)

    def test_create_update_port_qos_policy(self):
        nb_api = self.driver.nb_api
        qos_obj = self._test_create_policy()
        kwargs = {'qos_policy_id': qos_obj['id']}
        with self.subnet(enable_dhcp=False) as subnet:
            with self.port(subnet=subnet,
                           arg_list=('qos_policy_id',),
                           **kwargs) as p:
                port_id = p['port']['id']
                self.assertTrue(nb_api.create_lport.called)
                called_args = nb_api.create_lport.call_args_list[0][1]
                self.assertEqual(qos_obj['id'],
                                 called_args.get('qos_policy_id'))

                data = {'port': {'qos_policy_id': None}}
                req = self.new_update_request('ports', data, port_id)
                req.get_response(self.api)
                self.assertTrue(nb_api.update_lport.called)
                called_args = nb_api.update_lport.call_args_list[0][1]
                self.assertIsNone(called_args.get('qos_policy_id'))
