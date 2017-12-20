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

import time

from ryu.lib.packet import arp

from dragonflow.controller.common import constants as const
from dragonflow.tests.common import constants as test_const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestOVSFlowsForActivePortDectionApp(test_base.DFTestBase):

    def _get_sending_arp_to_controller_flows(self, port_key, arp_op):
        ovs_flows_parser = utils.OvsFlowsParser()
        flows = ovs_flows_parser.dump(self.integration_bridge)
        expected_in_port = "reg6=" + hex(port_key)
        expected_arp_op = "arp_op=" + str(arp_op)
        expected_actions = "CONTROLLER:65535," + "goto_table:" + \
                           str(const.L2_LOOKUP_TABLE)
        flows = [flow for flow in flows
                 if ((expected_in_port in flow['match']) and
                     (expected_arp_op in flow['match']) and
                     ('arp' in flow['match']) and
                     (flow['table'] == str(const.ARP_TABLE)) and
                     (flow['actions'] == expected_actions))]
        return flows

    def _get_sending_arp_reply_to_controller_flows(self, port_key):
        return self._get_sending_arp_to_controller_flows(port_key,
                                                         str(arp.ARP_REPLY))

    def _get_sending_gratuitous_arp_to_controller_flows(self, port_key):
        return self._get_sending_arp_to_controller_flows(port_key,
                                                         str(arp.ARP_REQUEST))

    def _check_sending_arp_reply_to_controller_flows(self, port_key, ip=None):
        flows = self._get_sending_arp_reply_to_controller_flows(port_key)
        expected_arp_tpa = '0.0.0.0'
        for flow in flows:
            if ip is not None:
                if expected_arp_tpa not in flow['match']:
                    continue
                expected_arp_spa = 'arp_spa=' + ip
                if expected_arp_spa not in flow['match']:
                    continue
            return True
        return False

    def _check_sending_gratuitous_arp_to_controller_flows(self, port_key,
                                                          ip=None):
        flows = self._get_sending_gratuitous_arp_to_controller_flows(port_key)
        for flow in flows:
            if ip is not None:
                expected_arp_spa = 'arp_spa=' + ip
                expected_arp_tpa = 'arp_tpa=' + ip
                if (expected_arp_spa not in flow['match']) or \
                        (expected_arp_tpa not in flow['match']):
                    continue
            return True

        return False

    def test_sending_arp_to_controller_flows(self):
        """
        Add a VM with allowed address pairs configuration. Verify related
        flows is there.
        """
        if not self.check_app_loaded("active_port_detection"):
            self.skipTest("ActivePortDetectionApp is not enabled")

        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'aap_test'})
        self.addCleanup(network.close)
        subnet_obj = self.store(objects.SubnetTestObj(
            self.neutron,
            self.nb_api,
            network_id,
        ))

        subnet = {'network_id': network_id,
                  'cidr': '192.168.97.0/24',
                  'gateway_ip': '192.168.97.1',
                  'ip_version': 4,
                  'name': 'aap_test',
                  'enable_dhcp': True}
        subnet_obj.create(subnet)
        self.addCleanup(subnet_obj.close)

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm_id = vm.create(network=network)
        self.addCleanup(vm.close)

        vm_port_id = self.vswitch_api.get_port_id_by_vm_id(vm_id)
        self.assertIsNotNone(vm_port_id)

        vm_port = objects.PortTestObj(self.neutron, self.nb_api, network_id,
                                      vm_port_id)
        self.addCleanup(vm_port.close)
        of_port = self.vswitch_api.get_port_ofport_by_id(vm_port_id)
        self.assertIsNotNone(of_port)
        vm_lport = vm_port.get_logical_port()
        self.assertIsNotNone(vm_lport)
        result = self._check_sending_arp_reply_to_controller_flows(
            vm_lport.unique_key)
        self.assertFalse(result)
        result = self._check_sending_gratuitous_arp_to_controller_flows(
            vm_lport.unique_key)
        self.assertFalse(result)

        ip_address1 = '192.168.97.100'
        mac_address1 = '1A:22:33:44:55:66'
        allowed_address_pairs1 = [{'ip_address': ip_address1,
                                   'mac_address': mac_address1}]
        vm_port.update({'allowed_address_pairs': allowed_address_pairs1})

        time.sleep(test_const.DEFAULT_CMD_TIMEOUT)

        result = self._check_sending_arp_reply_to_controller_flows(
            vm_lport.unique_key, ip_address1)
        self.assertTrue(result)
        result = self._check_sending_gratuitous_arp_to_controller_flows(
            vm_lport.unique_key, ip_address1)
        self.assertTrue(result)

        ip_address2 = '192.168.97.101'
        allowed_address_pairs2 = [{'ip_address': ip_address2}]
        vm_port.update({'allowed_address_pairs': allowed_address_pairs2})

        time.sleep(test_const.DEFAULT_CMD_TIMEOUT)

        result = self._check_sending_arp_reply_to_controller_flows(
            vm_lport.unique_key, ip_address1)
        self.assertFalse(result)
        result = self._check_sending_gratuitous_arp_to_controller_flows(
            vm_lport.unique_key, ip_address1)
        self.assertFalse(result)
        result = self._check_sending_arp_reply_to_controller_flows(
            vm_lport.unique_key, ip_address2)
        self.assertTrue(result)
        result = self._check_sending_gratuitous_arp_to_controller_flows(
            vm_lport.unique_key, ip_address2)
        self.assertTrue(result)

        vm.close()

        time.sleep(test_const.DEFAULT_CMD_TIMEOUT)

        result = self._check_sending_arp_reply_to_controller_flows(
            vm_lport.unique_key, ip_address2)
        self.assertFalse(result)
        result = self._check_sending_gratuitous_arp_to_controller_flows(
            vm_lport.unique_key, ip_address2)
        self.assertFalse(result)
