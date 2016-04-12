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

    def test_topology_create_vm(self):
        """
        Add a VM. Verify it's flow is there.
        Remove the VM and verify it's flow is removed.
        """
        network = self._create_network()
        vm1 = self._create_vm(network)
        self._remove_vm(vm1)

    def test_topology_create_vm2(self):
        """
        Add two VMs. Verify their flows are there.
        Remove the VMs and verify flows added for the VMs are removed.
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
        vm_mac = vm.get_first_mac()
        self.assertTrue(vm_mac is not None)
        vm_flows = self._get_vm_flows(vm_mac)
        self.assertTrue(any(vm_flows))
        return vm

    def _remove_vm(self, vm):
        vm_mac = vm.get_first_mac()
        vm.server.stop()
        vm.close()
        wait_until_none(
            lambda: 1 if any(self._get_vm_flows(vm_mac)) else None, timeout=60,
            exception=Exception('VM flow was not deleted')
        )

    def _get_vm_flows(self, vm_mac):
        ovs_flows_parser = OvsFlowsParser()
        flows = ovs_flows_parser.dump()
        flows = [flow for flow in flows if
                 flow['table'] == str(const.ARP_TABLE) and
                 vm_mac in flow['actions']]
        return flows
