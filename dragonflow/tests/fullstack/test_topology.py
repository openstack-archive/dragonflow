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

from dragonflow.controller.common import constants as const
from dragonflow.tests.common.utils import OvsFlowsParser, wait_until_none
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
        network = self._create_network()
        vm1 = self._create_vm(network)
        self._remove_vm(vm1)

    def test_topology_create_vm2(self):
        """
        Add two VMs. Verify it's ARP flow is there.
        """
        network = self._create_network()
        vm1 = self._create_vm(network)
        vm2 = self._create_vm(network)
        self._remove_vm(vm1)
        self._remove_vm(vm2)

    def _create_network(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'private'})
        self.assertTrue(network.exists())
        subnet = self.store(objects.SubnetTestObj(
            self.neutron,
            self.nb_api,
            network_id,
        ))
        subnet.create()
        self.assertTrue(subnet.exists())
        return network

    def _create_vm(self, network):
        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)
        vm_ip = vm.get_first_ipv4()
        self.assertTrue(vm_ip is not None)
        vm_flows = self._get_vm_flows(vm_ip)
        self.assertTrue(any(vm_flows))
        return vm

    def _remove_vm(self, vm):
        vm_ip = vm.get_first_ipv4()
        vm.server.stop()
        vm.close()
        wait_until_none(
            lambda: 1 if any(self._get_vm_flows(vm_ip)) else None, timeout=20,
            exception=Exception('VM port was not deleted')
        )
        # sometimes, the network can't be cleared successfully.
        wait_until_none(
            lambda: self._git_vm_port(vm_ip), timeout=60, sleep=6,
            exception=Exception('VM port was not deleted')
        )

    def _get_vm_flows(self, vm_ip):
        ovs_flows_parser = OvsFlowsParser()
        flows = ovs_flows_parser.dump()
        flows = [flow for flow in flows if
                 flow['table'] == str(const.ARP_TABLE) + ',' and
                 ('arp_tpa=' + vm_ip + ',') in flow['match']]
        return flows

    def _git_vm_port(self, vm_ip):
        ports = self.neutron.list_ports()
        if ports is None:
            return None
        for port in ports['ports']:
            for fixed_ip in port['fixed_ips']:
                if vm_ip == fixed_ip['ip_address']:
                    return port
