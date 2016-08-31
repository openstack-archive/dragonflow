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

from dragonflow.tests.common import utils

from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

from neutron.agent.linux.utils import wait_until_true


class TestRemotePort(test_base.DFTestBase):

    def test_remote_port(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'network1'})
        self.assertTrue(network.exists())

        subnet_info = {'network_id': network_id,
                       'cidr': '192.168.150.0/24',
                       'gateway_ip': '192.168.150.1',
                       'ip_version': 4,
                       'name': 'subnet1',
                       'enable_dhcp': True}
        subnet = self.store(objects.SubnetTestObj(self.neutron,
                                                  self.nb_api,
                                                  network_id=network_id))
        subnet.create(subnet_info)
        self.assertTrue(subnet.exists())

        port = self.store(objects.PortTestObj(
                self.neutron, self.nb_api, network_id))
        port_body = {
                'admin_state_up': True,
                'name': 'port1',
                'network_id': network_id,
                'binding:profile': {
                    'port_key': 'remote_port',
                    'host_ip': '10.10.10.10'
                }
        }
        port.create(port=port_body)
        self.assertTrue(port.exists())

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)

        self.assertTrue(vm._wait_for_server_ready(30))
        ip = vm.get_first_ipv4()
        self.assertIsNotNone(ip)
        mac = vm.get_first_mac()
        self.assertIsNotNone(mac)

        ovsdb = utils.OvsDBParser()
        wait_until_true(
            lambda: self._get_wanted_tunnel_port(ovsdb, '10.10.10.10'),
            timeout=30, sleep=2,
            exception=Exception('Could not get wanted tunnel port')
        )

        port.close()
        self.assertFalse(port.exists())

        utils.wait_until_none(
            lambda: ovsdb.get_tunnel_ofport('10.10.10.10'),
            timeout=30, sleep=2,
            exception=Exception('Could not delete wanted tunnel port')
        )

        vm.server.stop()
        vm.close()

        subnet.close()
        network.close()

    def _get_wanted_tunnel_port(self, ovsdb, chassis_id):
        if ovsdb.get_tunnel_ofport(chassis_id):
            return True
        return False
