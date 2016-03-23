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

from dragonflow.controller.common import constants as const
from dragonflow.tests.common.utils import OvsFlowsParser
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestTopology(test_base.DFTestBase):

    def setUp(self):
        super(TestTopology, self).setUp()

    def tearDown(self):
        super(TestTopology, self).tearDown()

    def test_topology_create_vm(self):
        """
        Add a VM. Verify it's ARP flow is there.
        """
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'private'})
        subnet = {'network_id': network_id,
            'cidr': '192.168.101.0/24',
            'gateway_ip': '192.168.101.1',
            'ip_version': 4,
            'name': 'private',
            'enable_dhcp': True}
        subnet = self.neutron.create_subnet({'subnet': subnet})

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        vm_ip = vm.get_first_ipv4()
        vm_flows = self._get_vm_flows(vm_ip)
        self.assertTrue(any(vm_flows))
        vm.server.stop()
        vm.close()
        self.assertTrue(self._wait_for_flow_removal(vm_ip, 30))
        # sometimes, the network can't be cleared successfully.
        time.sleep(10)

    def _get_vm_flows(self, vm_ip):
        ovs_flows_parser = OvsFlowsParser()
        flows = ovs_flows_parser.dump()
        flows = [flow for flow in flows if
                 flow['table'] == str(const.ARP_TABLE) + ',' and
                 ('arp_tpa=' + vm_ip + ',') in flow['match']]
        return flows

    def _wait_for_flow_removal(self, vm_ip, timeout):
        while timeout > 0:
            vm_flows = self._get_vm_flows(vm_ip)
            if not any(vm_flows):
                return True
            timeout -= 1
            time.sleep(1)
        return False
