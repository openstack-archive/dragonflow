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
from neutron.objects.qos import rule
from neutron_lib.plugins import constants as service_constants
from neutron_lib.plugins import directory

from dragonflow.db.models import l2
from dragonflow.db.models import qos
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_mech_driver


class TestDfQosDriver(test_mech_driver.DFMechanismDriverTestCase):

    """Test case of df qos notification drvier"""

    def get_additional_service_plugins(self):
        p = super(TestDfQosDriver, self).get_additional_service_plugins()
        p.update({'qos_plugin_name': 'qos'})
        return p

    def setUp(self):
        if 'qos' not in self._extension_drivers:
            self._extension_drivers.append('qos')

        mock.patch('dragonflow.db.neutron.lockedobjects_db.wrap_db_lock',
                   side_effect=utils.empty_wrapper).start()
        mock.patch('dragonflow.neutron.services.qos.drivers.df_qos._driver',
                   new=None).start()
        super(TestDfQosDriver, self).setUp()
        self.qos_plugin = directory.get_plugin(service_constants.QOS)

        # Find by name
        self.qos_driver = [
            d for d in self.qos_plugin.driver_manager._drivers
            if d.name == 'df'
        ].pop()

    def _test_create_policy(self):
        qos_policy = {'policy': {'name': "policy1", 'project_id': 'project1'}}
        qos_obj = self.qos_plugin.create_policy(self.context, qos_policy)
        self.assertEqual(qos_obj['revision_number'], 0)
        self.qos_driver.nb_api.create.assert_called_with(qos.QosPolicy(
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
        new_qos_obj = self.qos_plugin.update_policy(
            self.context, qos_obj['id'], {'policy': {'name': 'policy2'}})
        self.assertGreater(new_qos_obj['revision_number'],
                           qos_obj['revision_number'])
        self.qos_driver.nb_api.update.assert_called_with(qos.QosPolicy(
            id=qos_obj['id'],
            topic='project1',
            name='policy2',
            rules=[],
            version=new_qos_obj['revision_number']))

    def test_create_delete_policy_rule(self):
        qos_obj = self._test_create_policy()
        qos_rule = {'max_burst_kbps': 1000,
                    'max_kbps': 100}
        qos_rule_obj = self.qos_plugin.create_policy_rule(
            self.context, rule.QosBandwidthLimitRule,
            qos_obj['id'], {'bandwidth_limit_rule': qos_rule})
        qos_rule_obj.pop('qos_policy_id', None)
        new_qos_obj = self.qos_plugin.get_policy(self.context, qos_obj['id'])
        self.assertGreater(new_qos_obj['revision_number'],
                           qos_obj['revision_number'])
        self.qos_driver.nb_api.update.assert_called_with(qos.QosPolicy(
            id=qos_obj['id'],
            topic='project1',
            name='policy1',
            rules=[qos_rule_obj],
            version=new_qos_obj['revision_number']))

        self.qos_plugin.delete_policy_rule(self.context,
                                           rule.QosBandwidthLimitRule,
                                           qos_rule_obj['id'],
                                           qos_obj['id'])
        newer_qos_obj = self.qos_plugin.get_policy(self.context, qos_obj['id'])
        self.assertGreater(newer_qos_obj['revision_number'],
                           new_qos_obj['revision_number'])
        self.qos_driver.nb_api.update.assert_called_with(qos.QosPolicy(
            id=qos_obj['id'],
            topic='project1',
            name='policy1',
            rules=[],
            version=newer_qos_obj['revision_number']))

    def test_delete_policy(self):
        qos_obj = self._test_create_policy()
        self.qos_plugin.delete_policy(self.context, qos_obj['id'])
        self.qos_driver.nb_api.delete.assert_called_with(qos.QosPolicy(
            id=qos_obj['id']))

    def test_create_update_network_qos_policy(self):
        nb_api = self.qos_driver.nb_api
        qos_obj = self._test_create_policy()
        kwargs = {'qos_policy_id': qos_obj['id']}
        with self.network(arg_list=('qos_policy_id',), **kwargs) as n:
            network_id = n['network']['id']
            self.assertTrue(nb_api.create.called)
            # Excepted call order for nb_api.create:
            # QosPolicy, SecurityGroup, LogicalSwitch.
            # Expected index for LogicalSwitch is 2.
            lswitch_arg = nb_api.create.call_args_list[2][0][0]
            self.assertEqual(qos_obj['id'], lswitch_arg.qos_policy.id)

            data = {'network': {'qos_policy_id': None}}
            req = self.new_update_request('networks', data, network_id)
            req.get_response(self.api)
            self.assertTrue(nb_api.update.called)
            called_args = nb_api.update.call_args_list[0][0][0]
            self.assertIsNone(called_args.qos_policy)

    def test_create_update_port_qos_policy(self):
        nb_api = self.qos_driver.nb_api
        qos_obj = self._test_create_policy()
        kwargs = {'qos_policy_id': qos_obj['id']}
        with self.subnet(enable_dhcp=False) as subnet:
            nb_api.create.reset_mock()
            with self.port(subnet=subnet,
                           arg_list=('qos_policy_id',),
                           **kwargs) as p:
                port_id = p['port']['id']
                nb_api.create.assert_called_once()
                lport = nb_api.create.call_args_list[0][0][0]
                self.assertIsInstance(lport, l2.LogicalPort)
                self.assertEqual(qos_obj['id'], lport.qos_policy.id)

                nb_api.update.reset_mock()
                data = {'port': {'qos_policy_id': None}}
                req = self.new_update_request('ports', data, port_id)
                req.get_response(self.api)
                nb_api.update.assert_called_once()
                lport = nb_api.update.call_args_list[0][0][0]
                self.assertIsInstance(lport, l2.LogicalPort)
                self.assertIsNone(lport.qos_policy)
