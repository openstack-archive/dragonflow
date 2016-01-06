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

from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestNeutronAPIandDB(test_base.DFTestBase):

    def setUp(self):
        super(TestNeutronAPIandDB, self).setUp()

    def test_create_network(self):
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network.create()
        self.assertTrue(network.exists())
        network.delete()
        self.assertFalse(network.exists())

    def test_dhcp_port_created(self):
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = {'network_id': network_id,
            'cidr': '10.1.0.0/24',
            'gateway_ip': '10.1.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        self.neutron.create_subnet({'subnet': subnet})
        ports = self.nb_api.get_all_logical_ports()
        dhcp_ports_found = 0
        for port in ports:
            if port.get_lswitch_id() == network_id:
                if port.get_device_owner() == 'network:dhcp':
                    dhcp_ports_found += 1
        network.delete()
        self.assertEqual(dhcp_ports_found, 1)
        ports = self.nb_api.get_all_logical_ports()
        dhcp_ports_found = 0
        for port in ports:
            if port.get_lswitch_id() == network_id:
                if port.get_device_owner() == 'network:dhcp':
                    dhcp_ports_found += 1
        self.assertEqual(dhcp_ports_found, 0)

    def test_create_delete_router(self):
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        router.create()
        self.assertTrue(router.exists())
        router.delete()
        self.assertFalse(router.exists())

    def test_create_router_interface(self):
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = {'subnets': [{'cidr': '192.168.199.0/24',
                  'ip_version': 4, 'network_id': network_id}]}
        subnets = self.neutron.create_subnet(body=subnet)
        subnet = subnets['subnets'][0]
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet['id']}
        port = self.neutron.add_interface_router(router_id, body=subnet_msg)
        port2 = self.nb_api.get_logical_port(port['port_id'])
        self.assertIsNotNone(port2)
        router.delete()
        port2 = self.nb_api.get_logical_port(port['port_id'])
        self.assertIsNone(port2)
        network.delete()
        self.assertFalse(router.exists())
        self.assertFalse(network.exists())

    def test_create_port(self):
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        port = {'admin_state_up': True, 'name': 'port1',
                'network_id': network_id}
        port = self.neutron.create_port(body={'port': port})
        port2 = self.nb_api.get_logical_port(port['port']['id'])
        self.assertIsNotNone(port2)
        self.assertEqual(network_id, port2.get_lswitch_id())
        self.neutron.delete_port(port['port']['id'])
        port2 = self.nb_api.get_logical_port(port['port']['id'])
        self.assertIsNone(port2)
        network.delete()
        self.assertFalse(network.exists())
