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
from neutronclient.common import exceptions as n_exc


class TestNeutronAPIandDB(test_base.DFTestBase):

    def setUp(self):
        super(TestNeutronAPIandDB, self).setUp()

    def test_create_network(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network.create()
        self.assertTrue(network.exists())
        network.delete()
        self.assertFalse(network.exists())

    def test_dhcp_port_created(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
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

    def test_create_delete_subnet(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = self.store(objects.SubnetTestObj(
            self.neutron,
            self.nb_api,
            network_id,
        ))
        subnet_id = subnet.create()
        self.assertTrue(subnet.exists())
        self.assertEqual(subnet_id, subnet.get_subnet().get_id())
        subnet.delete()
        self.assertFalse(subnet.exists())
        network.delete()

    def test_create_delete_router(self):
        router = self.store(objects.RouterTestObj(self.neutron, self.nb_api))
        router.create()
        self.assertTrue(router.exists())
        router.delete()
        self.assertFalse(router.exists())

    def test_create_router_interface(self):
        router = self.store(objects.RouterTestObj(self.neutron, self.nb_api))
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = self.store(objects.SubnetTestObj(
            self.neutron,
            self.nb_api,
            network_id,
        ))
        subnet_id = subnet.create()
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet_id}
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
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        self.assertTrue(network.exists())
        port = self.store(objects.PortTestObj(self.neutron,
                                  self.nb_api, network_id))
        port.create()
        self.assertTrue(port.exists())
        self.assertEqual(network_id, port.get_logical_port().get_lswitch_id())
        port.delete()
        self.assertFalse(port.exists())
        network.delete()
        self.assertFalse(network.exists())

    def test_delete_router_interface_port(self):
        router = self.store(objects.RouterTestObj(self.neutron, self.nb_api))
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = self.store(objects.SubnetTestObj(
            self.neutron,
            self.nb_api,
            network_id,
        ))
        subnet_id = subnet.create({
            'cidr': '91.126.188.0/24',
            'ip_version': 4,
            'network_id': network_id
        })
        router_id = router.create()
        self.assertTrue(router.exists())
        interface_msg = {'subnet_id': subnet_id}
        router_l = self.neutron.add_interface_router(router_id,
                                                     body=interface_msg)
        routers = self.nb_api.get_routers()
        router2 = None
        for r in routers:
            if r.get_name() == router_l['id']:
                router2 = r
                break
        self.assertIsNotNone(router2)
        interface_port = self.neutron.show_port(router_l['port_id'])
        self.assertRaises(n_exc.Conflict, self.neutron.delete_port,
                          interface_port['port']['id'])
        self.assertIsNotNone(self.nb_api.
                             get_logical_port(interface_port['port']['id']))
        self.neutron.remove_interface_router(router.router_id,
                                             body=interface_msg)
        port2 = self.nb_api.get_logical_port(interface_port['port']['id'])
        self.assertIsNone(port2)
        router.delete()
        network.delete()
        self.assertFalse(router.exists())
        self.assertFalse(network.exists())

'''
The following tests are for list networks/routers/ports/subnets API.
They require seqential execution because another running test can break them.
To be able to run tests sequentially, testr must be started with
"--concurrency=1" argument. You can do it in tools/pretty_tox.sh file.

Currently it has the following falue:
--testr-args="--concurrency=1 --subunit $TESTRARGS";
'''

'''
Sequential tests
    def test_list_networks(self):
        networks = self.neutron.list_networks()
        networks = networks['networks']
        #print("networks", networks)
        networks2 = list()
        for network in networks:
            networks2.append(network['id'])
        networks2.sort()
        switches = self.nb_api.get_all_logical_switches()
        switches2 = list()
        for switch in switches:
            switches2.append(switch.get_id())
        switches2.sort()
        self.assertEqual(networks2, switches2)

    def test_list_subnets(self):
        subnets = self.neutron.list_subnets(retrieve_all=True)
        subnets = subnets['subnets']
        #print("subnets", subnets)
        subnets2 = list()
        for subnet in subnets:
            subnets2.append(subnet['id'])
        subnets2.sort()
        switches = self.nb_api.get_all_logical_switches()
        subnets3 = list()
        for switch in switches:
            subnets = switch.get_subnets()
            for subnet in subnets:
                subnets3.append(subnet.get_id())
        subnets3.sort()
        self.assertEqual(subnets2, subnets3)

    def test_list_local_ports(self):
        ports = self.neutron.list_ports(retrieve_all=True)
        ports = ports['ports']
        ports2 = list()
        for port in ports:
            if port['binding:host_id'] is not None:
                if port['device_owner'] != 'network:router_gateway':
                    ports2.append(port['id'])
        ports2.sort()
        lports = self.nb_api.get_all_logical_ports()
        lports2 = list()
        for lport in lports:
            lports2.append(lport.get_id())
        lports2.sort()
        self.assertEqual(ports2, lports2)

    def test_list_routers(self):
        routers = self.neutron.list_routers(retrieve_all=True)
        routers = routers['routers']
        routers1 = list()
        for router in routers:
            routers1.append(router['id'])
        routers1.sort()
        routers_in_db = self.nb_api.get_routers()
        routers2 = list()
        for router in routers_in_db:
            routers2.append(router.get_name())
        routers2.sort()
        self.assertEqual(routers1, routers2)
'''
