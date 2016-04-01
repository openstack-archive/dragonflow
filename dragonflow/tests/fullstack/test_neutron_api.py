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

import contextlib

from oslo_concurrency import lockutils
from oslo_log import log

from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects
from neutronclient.common import exceptions as n_exc


LOG = log.getLogger(__name__)


class TestNeutronAPIandDB(test_base.DFTestBase):

    def setUp(self):
        super(TestNeutronAPIandDB, self).setUp()

    def test_create_network(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network.create()
        self.assertTrue(network.exists())
        network.close()
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
        ports = utils.wait_until_is_and_return(
            lambda: self.nb_api.get_all_logical_ports(),
            exception=Exception('No ports assigned in subnet')
        )
        dhcp_ports_found = 0
        for port in ports:
            if port.get_lswitch_id() == network_id:
                if port.get_device_owner() == 'network:dhcp':
                    dhcp_ports_found += 1
        network.close()
        self.assertEqual(dhcp_ports_found, 1)
        ports = self.nb_api.get_all_logical_ports()
        dhcp_ports_found = 0
        for port in ports:
            if port.get_lswitch_id() == network_id:
                if port.get_device_owner() == 'network:dhcp':
                    dhcp_ports_found += 1
        self.assertEqual(dhcp_ports_found, 0)

    def test_create_delete_subnet(self):
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
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
        subnet.close()
        self.assertFalse(subnet.exists())
        network.close()

    def test_create_delete_router(self):
        router = self.store(objects.RouterTestObj(self.neutron, self.nb_api))
        router.create()
        self.assertTrue(router.exists())
        router.close()
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
        router.close()
        utils.wait_until_none(
            lambda: self.nb_api.get_logical_port(port['port_id']),
            exception=Exception('Port was not deleted')
        )
        subnet.close()
        network.close()
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
        port.close()
        self.assertFalse(port.exists())
        network.close()
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
        subnet.close()
        router.close()
        network.close()
        self.assertFalse(router.exists())
        self.assertFalse(network.exists())

    def test_create_delete_security_group(self):
        secgroup = self.store(
                        objects.SecGroupTestObj(self.neutron, self.nb_api))
        secgroup.create()
        self.assertTrue(secgroup.exists())
        secgroup.close()
        self.assertFalse(secgroup.exists())

    def test_create_delete_security_group_rule(self):
        secgroup = self.store(
                        objects.SecGroupTestObj(self.neutron, self.nb_api))
        secgroup.create()
        self.assertTrue(secgroup.exists())
        secrule_id = secgroup.rule_create()
        self.assertTrue(secgroup.rule_exists(secrule_id))
        secgroup.rule_delete(secrule_id)
        self.assertFalse(secgroup.rule_exists(secrule_id))
        secgroup.close()
        self.assertFalse(secgroup.exists())

    @contextlib.contextmanager
    def _prepare_ext_net(self):
        external_net = objects.find_first_network(self.neutron,
                                                  {'router:external': True})
        if not external_net:
            network = self.store(
                objects.NetworkTestObj(self.neutron, self.nb_api))
            external_net_para = {'name': 'public', 'router:external': True}
            external_network_id = network.create(network=external_net_para)
            self.assertTrue(network.exists())
            ext_subnet = self.store(objects.SubnetTestObj(
                self.neutron,
                self.nb_api,
                external_network_id,
            ))
            external_subnet_para = {'cidr': '192.168.199.0/24',
                      'ip_version': 4, 'network_id': external_network_id}
            ext_subnet.create(external_subnet_para)
            self.assertTrue(ext_subnet.exists())
        else:
            external_network_id = external_net['id']
        self.assertIsNotNone(external_network_id)

        # return external network
        yield external_network_id

        if not external_net:
            ext_subnet.close()
            self.assertFalse(ext_subnet.exists())
            network.close()
            self.assertFalse(network.exists())

    @lockutils.synchronized('need-external-net')
    def test_associate_floatingip(self):
        with self._prepare_ext_net() as external_network_id:
            router = self.store(
                objects.RouterTestObj(self.neutron, self.nb_api))
            fip = self.store(
                objects.FloatingipTestObj(self.neutron, self.nb_api))

            router_para = {'name': 'myrouter1', 'admin_state_up': True,
                 'external_gateway_info': {"network_id": external_network_id}}
            router.create(router=router_para)
            self.assertTrue(router.exists())

            # private network
            private_network = self.store(
                objects.NetworkTestObj(self.neutron, self.nb_api))
            private_network_id = private_network.create(
                network={'name': 'private'})
            self.assertTrue(private_network.exists())

            # private subnet
            priv_subnet = self.store(objects.SubnetTestObj(
                self.neutron,
                self.nb_api,
                private_network_id,
            ))
            private_subnet_para = {'cidr': '10.0.0.0/24',
                  'ip_version': 4, 'network_id': private_network_id}
            priv_subnet_id = priv_subnet.create(private_subnet_para)
            self.assertTrue(priv_subnet.exists())
            router_interface = router.add_interface(subnet_id=priv_subnet_id)
            router_lport = self.nb_api.get_logical_port(
                router_interface['port_id'])
            self.assertIsNotNone(router_lport)

            port = self.store(
                objects.PortTestObj(self.neutron,
                                self.nb_api, private_network_id))
            port_id = port.create()
            self.assertIsNotNone(port.get_logical_port())

            fip_para = {'floating_network_id': external_network_id}
            # create
            fip.create(fip_para)
            self.assertTrue(fip.exists())

            # associate with port
            fip.update({'port_id': port_id})
            fip_obj = fip.get_floatingip()
            self.assertEqual(fip_obj.lport_id, port_id)

            fip.close()
            self.assertFalse(fip.exists())
            port.close()
            self.assertFalse(port.exists())
            router.close()
            self.assertFalse(router.exists())
            priv_subnet.close()
            self.assertFalse(priv_subnet.exists())

    @lockutils.synchronized('need-external-net')
    def test_disassociate_floatingip(self):
        with self._prepare_ext_net() as external_network_id:
            router = self.store(
                objects.RouterTestObj(self.neutron, self.nb_api))
            fip = self.store(
                objects.FloatingipTestObj(self.neutron, self.nb_api))

            router_para = {'name': 'myrouter1', 'admin_state_up': True,
                 'external_gateway_info': {"network_id": external_network_id}}
            router.create(router=router_para)
            self.assertTrue(router.exists())

            # private network
            private_network = self.store(
                objects.NetworkTestObj(self.neutron, self.nb_api))
            private_network_id = private_network.create(
                network={'name': 'private'})
            self.assertTrue(private_network.exists())
            # private subnet
            priv_subnet = self.store(objects.SubnetTestObj(
                self.neutron,
                self.nb_api,
                private_network_id,
            ))
            private_subnet_para = {'cidr': '10.0.0.0/24',
                  'ip_version': 4, 'network_id': private_network_id}
            priv_subnet_id = priv_subnet.create(private_subnet_para)
            self.assertTrue(priv_subnet.exists())
            router_interface = router.add_interface(subnet_id=priv_subnet_id)
            router_lport = self.nb_api.get_logical_port(
                router_interface['port_id'])
            self.assertIsNotNone(router_lport)

            port = self.store(
                objects.PortTestObj(self.neutron,
                                self.nb_api, private_network_id))
            port_id = port.create()
            self.assertIsNotNone(port.get_logical_port())

            fip_para = {'floating_network_id': external_network_id,
                'port_id': port_id}
            # create
            fip.create(fip_para)
            self.assertTrue(fip.exists())

            # disassociate with port
            fip.update({})
            fip_obj = fip.get_floatingip()
            self.assertIsNone(fip_obj.lport_id)

            fip.close()
            self.assertFalse(fip.exists())
            port.close()
            self.assertFalse(port.exists())
            router.close()
            self.assertFalse(router.exists())
            priv_subnet.close()
            self.assertFalse(priv_subnet.exists())
