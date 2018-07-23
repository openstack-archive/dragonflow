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

import netaddr
from neutronclient.common import exceptions as n_exc
from oslo_concurrency import lockutils

from dragonflow.db.models import host_route
from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.db.models import secgroups
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestNeutronAPIandDB(test_base.DFTestBase):

    def setUp(self):
        super(TestNeutronAPIandDB, self).setUp()

    def test_create_network(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network.create()
        self.assertTrue(network.exists())
        network.close()
        self.assertFalse(network.exists())

    def test_create_network_with_mtu(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network.create()
        self.assertTrue(network.exists())
        netobj = network.get_network()
        lswitch = self.nb_api.get(l2.LogicalSwitch(
            id=netobj['network']['id'], topic=netobj['network']['tenant_id']))
        net_mtu = lswitch.mtu
        self.assertEqual(netobj['network']['mtu'], net_mtu)
        network.close()
        self.assertFalse(network.exists())

    def test_dhcp_port_created(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
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
            lambda: self.nb_api.get_all(l2.LogicalPort),
            exception=Exception('No ports assigned in subnet')
        )
        dhcp_ports_found = 0
        for port in ports:
            if port.lswitch.id == network_id:
                if port.device_owner == 'network:dhcp':
                    dhcp_ports_found += 1
        network.close()
        self.assertEqual(1, dhcp_ports_found)
        ports = self.nb_api.get_all(l2.LogicalPort)
        dhcp_ports_found = 0
        for port in ports:
            if port.lswitch.id == network_id:
                if port.device_owner == 'network:dhcp':
                    dhcp_ports_found += 1
        self.assertEqual(0, dhcp_ports_found)

    def test_create_delete_subnet(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet_id = subnet.create()
        self.assertTrue(subnet.exists())
        self.assertEqual(subnet_id, subnet.get_subnet().id)
        subnet.close()
        self.assertFalse(subnet.exists())
        network.close()

    def test_create_subnet_with_host_routes(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet_data = {
            'cidr': '192.168.199.0/24',
            'ip_version': 4,
            'network_id': network_id,
            'host_routes': [
                {
                    'destination': '1.1.1.0/24',
                    'nexthop': '2.2.2.2'
                },
                {
                    'destination': '1.1.2.0/24',
                    'nexthop': '3.3.3.3'
                },
            ]
        }
        subnet.create(subnet_data)
        db_subnet = subnet.get_subnet()
        self.assertEqual(subnet_data['host_routes'],
                         [host_route.to_struct()
                          for host_route in db_subnet.host_routes])

    def test_create_delete_router(self):
        router = objects.RouterTestObj(self.neutron, self.nb_api)
        self.addCleanup(router.close)
        router_id = router.create()
        self.assertTrue(router.exists())
        version1 = self.nb_api.get(l3.LogicalRouter(id=router_id)).version
        router.update()
        self.assertTrue(router.exists())
        version2 = self.nb_api.get(l3.LogicalRouter(id=router_id)).version
        self.assertTrue(version1 != version2)
        router.close()
        self.assertFalse(router.exists())

    def test_create_router_interface(self):
        router = objects.RouterTestObj(self.neutron, self.nb_api)
        self.addCleanup(router.close)
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet_id = subnet.create()
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet_id}
        port = self.neutron.add_interface_router(router_id, body=subnet_msg)
        port2 = self.nb_api.get(l2.LogicalPort(id=port['port_id']))
        self.assertIsNotNone(port2)
        router.close()
        utils.wait_until_none(
            lambda: self.nb_api.get(l2.LogicalPort(id=port['port_id'])),
            exception=Exception('Port was not deleted')
        )
        subnet.close()
        network.close()
        self.assertFalse(router.exists())
        self.assertFalse(network.exists())

    def test_create_port(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())
        port = objects.PortTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(port.close)
        port.create()
        self.assertTrue(port.exists())
        self.assertEqual(network_id, port.get_logical_port().lswitch.id)
        port.close()
        self.assertFalse(port.exists())
        network.close()
        self.assertFalse(network.exists())

    def test_create_port_with_qospolicy(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())

        qospolicy = objects.QosPolicyTestObj(self.neutron, self.nb_api)
        self.addCleanup(qospolicy.close)
        qos_policy_id = qospolicy.create()
        self.assertTrue(qospolicy.exists())

        port = objects.PortTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(port.close)
        port_param = {
            'admin_state_up': True,
            'name': 'port1',
            'network_id': network_id,
            'qos_policy_id': qos_policy_id
        }
        port.create(port_param)
        self.assertTrue(port.exists())
        self.assertEqual(qos_policy_id,
                         port.get_logical_port().qos_policy.id)

        port.close()
        self.assertFalse(port.exists())
        network.close()
        self.assertFalse(network.exists())
        qospolicy.close()
        self.assertFalse(qospolicy.exists())

    def test_update_port_with_qospolicy(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())

        qospolicy = objects.QosPolicyTestObj(self.neutron, self.nb_api)
        self.addCleanup(qospolicy.close)
        qos_policy_id = qospolicy.create()
        self.assertTrue(qospolicy.exists())

        port = objects.PortTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(port.close)
        port.create()
        self.assertTrue(port.exists())

        port_param = {
            'admin_state_up': True,
            'name': 'port1',
            'qos_policy_id': qos_policy_id
        }
        port.update(port_param)
        self.assertEqual(qos_policy_id,
                         port.get_logical_port().qos_policy.id)

        port.close()
        self.assertFalse(port.exists())
        network.close()
        self.assertFalse(network.exists())
        qospolicy.close()
        self.assertFalse(qospolicy.exists())

    def test_delete_router_interface_port(self):
        router = objects.RouterTestObj(self.neutron, self.nb_api)
        self.addCleanup(router.close)
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
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
        routers = self.nb_api.get_all(l3.LogicalRouter)
        router2 = None
        for r in routers:
            if r.id == router_l['id']:
                router2 = r
                break
        self.assertIsNotNone(router2)
        interface_port = self.neutron.show_port(router_l['port_id'])
        self.assertRaises(n_exc.Conflict, self.neutron.delete_port,
                          interface_port['port']['id'])
        self.assertIsNotNone(self.nb_api.get(
            l2.LogicalPort(id=interface_port['port']['id'])))

        self.neutron.remove_interface_router(router.router_id,
                                             body=interface_msg)
        port2 = self.nb_api.get(
            l2.LogicalPort(id=interface_port['port']['id']))
        self.assertIsNone(port2)
        subnet.close()
        router.close()
        network.close()
        self.assertFalse(router.exists())
        self.assertFalse(network.exists())

    def test_create_delete_security_group(self):
        secgroup = objects.SecGroupTestObj(self.neutron, self.nb_api)
        self.addCleanup(secgroup.close)
        sg_id = secgroup.create()
        self.assertTrue(secgroup.exists())
        secgroup_obj = secgroups.SecurityGroup(id=sg_id)
        version1 = self.nb_api.get(secgroup_obj).version
        secgroup.update()
        self.assertTrue(secgroup.exists())
        secgroup_obj = secgroups.SecurityGroup(id=sg_id)
        version2 = self.nb_api.get(secgroup_obj).version
        self.assertNotEqual(version1, version2)
        secgroup.close()
        self.assertFalse(secgroup.exists())

    def test_create_delete_security_group_rule(self):
        secgroup = objects.SecGroupTestObj(self.neutron, self.nb_api)
        self.addCleanup(secgroup.close)
        secgroup.create()
        self.assertTrue(secgroup.exists())
        secrule_id = secgroup.rule_create()
        self.assertTrue(secgroup.rule_exists(secrule_id))
        secgroup.rule_delete(secrule_id)
        self.assertFalse(secgroup.rule_exists(secrule_id))
        secgroup.close()
        self.assertFalse(secgroup.exists())

    def test_create_delete_qos_policy(self):
        qospolicy = objects.QosPolicyTestObj(self.neutron, self.nb_api)
        self.addCleanup(qospolicy.close)
        policy_id = qospolicy.create()
        self.assertTrue(qospolicy.exists())
        rule = {'max_kbps': '1000', 'max_burst_kbps': '100'}
        qospolicy.create_rule(policy_id, rule, 'bandwidth_limit')
        self.assertTrue(qospolicy.exists())
        qospolicy.close()
        self.assertFalse(qospolicy.exists())

    @contextlib.contextmanager
    def _prepare_ext_net(self):
        external_net = objects.find_first_network(self.neutron,
                                                  {'router:external': True})
        if not external_net:
            network = objects.NetworkTestObj(self.neutron, self.nb_api)
            self.addCleanup(network.close)
            external_net_para = {'name': 'public', 'router:external': True}
            external_network_id = network.create(network=external_net_para)
            self.assertTrue(network.exists())
            ext_subnet = objects.SubnetTestObj(self.neutron, self.nb_api,
                                               external_network_id)
            self.addCleanup(ext_subnet.close)
            external_subnet_para = {'cidr': '192.168.199.0/24',
                                    'ip_version': 4,
                                    'network_id': external_network_id}
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
            router = objects.RouterTestObj(self.neutron, self.nb_api)
            self.addCleanup(router.close)
            fip = objects.FloatingipTestObj(self.neutron, self.nb_api)
            self.addCleanup(fip.close)

            router_para = {
                'name': 'myrouter1', 'admin_state_up': True,
                'external_gateway_info': {"network_id": external_network_id}}
            router.create(router=router_para)
            self.assertTrue(router.exists())

            # private network
            private_network = objects.NetworkTestObj(self.neutron, self.nb_api)
            self.addCleanup(private_network.close)
            private_network_id = private_network.create()
            self.assertTrue(private_network.exists())

            # private subnet
            priv_subnet = objects.SubnetTestObj(self.neutron, self.nb_api,
                                                private_network_id)
            self.addCleanup(priv_subnet.close)
            private_subnet_para = {'cidr': '10.0.0.0/24',
                                   'ip_version': 4,
                                   'network_id': private_network_id}
            priv_subnet_id = priv_subnet.create(private_subnet_para)
            self.assertTrue(priv_subnet.exists())
            router_interface = router.add_interface(subnet_id=priv_subnet_id)
            router_lport = self.nb_api.get(
                l2.LogicalPort(id=router_interface['port_id']))
            self.assertIsNotNone(router_lport)

            port = objects.PortTestObj(self.neutron, self.nb_api,
                                       private_network_id)
            self.addCleanup(port.close)
            port_id = port.create()
            self.assertIsNotNone(port.get_logical_port())

            fip_para = {'floating_network_id': external_network_id}
            # create
            fip.create(fip_para)
            self.assertTrue(fip.exists())

            # associate with port
            fip.update({'port_id': port_id})
            fip_obj = fip.get_floatingip()
            self.assertEqual(fip_obj.lport.id, port_id)

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
            router = objects.RouterTestObj(self.neutron, self.nb_api)
            self.addCleanup(router.close)
            fip = objects.FloatingipTestObj(self.neutron, self.nb_api)
            self.addCleanup(fip.close)

            router_para = {
                'name': 'myrouter1', 'admin_state_up': True,
                'external_gateway_info': {"network_id": external_network_id}}
            router.create(router=router_para)
            self.assertTrue(router.exists())

            # private network
            private_network = objects.NetworkTestObj(self.neutron, self.nb_api)
            self.addCleanup(private_network.close)
            private_network_id = private_network.create()
            self.assertTrue(private_network.exists())
            # private subnet
            priv_subnet = objects.SubnetTestObj(self.neutron, self.nb_api,
                                                private_network_id)
            self.addCleanup(priv_subnet.close)
            private_subnet_para = {'cidr': '10.0.0.0/24',
                                   'ip_version': 4,
                                   'network_id': private_network_id}
            priv_subnet_id = priv_subnet.create(private_subnet_para)
            self.assertTrue(priv_subnet.exists())
            router_interface = router.add_interface(subnet_id=priv_subnet_id)
            router_lport = self.nb_api.get(
                l2.LogicalPort(id=router_interface['port_id']))
            self.assertIsNotNone(router_lport)

            port = objects.PortTestObj(self.neutron, self.nb_api,
                                       private_network_id)
            self.addCleanup(port.close)
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
            self.assertIsNone(fip_obj.lport)

            fip.close()
            self.assertFalse(fip.exists())
            port.close()
            self.assertFalse(port.exists())
            router.close()
            self.assertFalse(router.exists())
            priv_subnet.close()
            self.assertFalse(priv_subnet.exists())

    def test_enable_disable_portsec(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())

        network2 = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network2.close)
        network_id2 = network2.create({'name': 'mynetwork1',
                                       'admin_state_up': True,
                                       'port_security_enabled': False})
        self.assertTrue(network2.exists())

        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet.create({
            'cidr': '192.168.125.0/24',
            'ip_version': 4,
            'network_id': network_id
        })
        self.assertTrue(subnet.exists())

        subnet2 = objects.SubnetTestObj(self.neutron, self.nb_api, network_id2)
        self.addCleanup(subnet2.close)
        subnet2.create({
            'cidr': '192.168.126.0/24',
            'ip_version': 4,
            'network_id': network_id2
        })
        self.assertTrue(subnet2.exists())

        network_portsec_switch = True
        port = objects.PortTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(port.close)
        port.create()
        lport = port.get_logical_port()
        self.assertIsNotNone(lport)
        real_switch = lport.port_security_enabled
        self.assertEqual(network_portsec_switch, real_switch)

        network_portsec_switch = False
        port = objects.PortTestObj(self.neutron, self.nb_api, network_id2)
        self.addCleanup(port.close)
        port.create()
        lport = port.get_logical_port()
        self.assertIsNotNone(lport)
        real_switch = lport.port_security_enabled
        self.assertEqual(network_portsec_switch, real_switch)

        port = objects.PortTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(port.close)
        expected_switch = False
        port.create({
            'admin_state_up': True,
            'name': 'port1',
            'network_id': network_id,
            'port_security_enabled': expected_switch
        })
        lport = port.get_logical_port()
        self.assertIsNotNone(lport)
        real_switch = lport.port_security_enabled
        self.assertEqual(expected_switch, real_switch)

        expected_switch = True
        port.update({'port_security_enabled': expected_switch})
        lport = port.get_logical_port()
        self.assertIsNotNone(lport)
        real_switch = lport.port_security_enabled
        self.assertEqual(expected_switch, real_switch)

    def test_add_remove_allowed_address_pairs(self):
        network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(network.close)
        network_id = network.create()
        self.assertTrue(network.exists())

        subnet = objects.SubnetTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(subnet.close)
        subnet.create({
            'cidr': '192.168.127.0/24',
            'ip_version': 4,
            'network_id': network_id
        })
        self.assertTrue(subnet.exists())

        port = objects.PortTestObj(self.neutron, self.nb_api, network_id)
        self.addCleanup(port.close)
        expected_pairs = [
                {"ip_address": "192.168.127.201",
                 "mac_address": "00:22:33:44:55:66"},
                {"ip_address": "192.168.127.202",
                 "mac_address": "22:22:33:44:55:66"}
        ]
        port.create({
            'admin_state_up': True,
            'name': 'port1',
            'network_id': network_id,
            'allowed_address_pairs': expected_pairs
        })
        lport = port.get_logical_port()
        self.assertIsNotNone(lport)
        real_pairs = [aap.to_struct() for aap in lport.allowed_address_pairs]
        self.assertItemsEqual(expected_pairs, real_pairs)

        expected_pairs = [
                {"ip_address": "192.168.127.211",
                 "mac_address": "00:22:33:44:55:66"},
                {"ip_address": "192.168.127.212",
                 "mac_address": "44:22:33:44:55:66"}
        ]
        port.update({'allowed_address_pairs': expected_pairs})
        lport = port.get_logical_port()
        self.assertIsNotNone(lport)
        real_pairs = [aap.to_struct() for aap in lport.allowed_address_pairs]
        self.assertItemsEqual(expected_pairs, real_pairs)

    def test_create_delete_bgp_peer(self):
        bgp_peer = objects.BGPPeerTestObj(self.neutron, self.nb_api)
        self.addCleanup(bgp_peer.close)
        bgp_peer.create()
        self.assertTrue(bgp_peer.exists())
        bgp_peer.close()
        self.assertFalse(bgp_peer.exists())

    def test_create_delete_bgp_speaker(self):
        bgp_speaker = objects.BGPSpeakerTestObj(self.neutron, self.nb_api)
        self.addCleanup(bgp_speaker.close)
        bgp_speaker.create()
        self.assertTrue(bgp_speaker.exists())
        bgp_speaker.close()
        self.assertFalse(bgp_speaker.exists())

    def test_add_remove_bgp_peer(self):
        bgp_peer = objects.BGPPeerTestObj(self.neutron, self.nb_api)
        self.addCleanup(bgp_peer.close)
        bgp_speaker = objects.BGPSpeakerTestObj(self.neutron, self.nb_api)
        self.addCleanup(bgp_speaker.close)
        bgp_peer.create()
        bgp_speaker.create()
        bgp_speaker.add_peer(bgp_peer.peer_id)
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        peers = [peer.id for peer in nb_bgp_speaker.peers]
        self.assertIn(bgp_peer.peer_id, peers)

        bgp_speaker.remove_peer(bgp_peer.peer_id)
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        peers = [peer.id for peer in nb_bgp_speaker.peers]
        self.assertNotIn(bgp_peer.peer_id, nb_bgp_speaker.peers)

    def test_delete_bgp_peer_update_bgp_speaker(self):
        bgp_peer = objects.BGPPeerTestObj(self.neutron, self.nb_api)
        self.addCleanup(bgp_peer.close)
        bgp_speaker = objects.BGPSpeakerTestObj(self.neutron, self.nb_api)
        self.addCleanup(bgp_speaker.close)
        bgp_peer.create()
        bgp_speaker.create()
        bgp_speaker.add_peer(bgp_peer.peer_id)
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        peers = [peer.id for peer in nb_bgp_speaker.peers]
        self.assertIn(bgp_peer.peer_id, peers)

        bgp_peer.close()
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        peers = [peer.id for peer in nb_bgp_speaker.peers]
        self.assertNotIn(bgp_peer.peer_id, nb_bgp_speaker.peers)

    @lockutils.synchronized('need-external-net')
    def test_add_remove_bgp_network(self):
        bgp_speaker = objects.BGPSpeakerTestObj(self.neutron, self.nb_api)
        self.addCleanup(bgp_speaker.close)
        bgp_speaker.create()
        address_scope = objects.AddressScopeTestObj(self.neutron, self.nb_api)
        self.addCleanup(address_scope.close)
        as_id = address_scope.create()
        private_subnetpool = objects.SubnetPoolTestObj(self.neutron,
                                                       self.nb_api)
        self.addCleanup(private_subnetpool.close)
        private_sp_id = private_subnetpool.create(
            subnetpool={'name': "private_sp",
                        'default_prefixlen': 24,
                        'prefixes': ["20.0.0.0/8"],
                        'address_scope_id': as_id})
        public_subnetpool = objects.SubnetPoolTestObj(self.neutron,
                                                      self.nb_api)
        self.addCleanup(public_subnetpool.close)
        public_sp_id = public_subnetpool.create(
            subnetpool={'name': "public_sp",
                        'default_prefixlen': 24,
                        'prefixes': ["172.24.4.0/24"],
                        'address_scope_id': as_id})
        public_network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(public_network.close)
        public_network_id = public_network.create(
            network={'name': 'public', 'router:external': True})
        public_subnet = objects.SubnetTestObj(self.neutron, self.nb_api,
                                              public_network_id)
        self.addCleanup(public_subnet.close)
        public_subnet.create(subnet={'ip_version': 4,
                                     'network_id': public_network_id,
                                     'subnetpool_id': public_sp_id})
        private_network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(private_network.close)
        private_network_id = private_network.create(network={'name': "public"})
        private_subnet = objects.SubnetTestObj(self.neutron, self.nb_api,
                                               private_network_id)
        self.addCleanup(private_subnet.close)
        private_sn_id = private_subnet.create(
            subnet={'ip_version': 4,
                    'network_id': private_network_id,
                    'subnetpool_id': private_sp_id})
        bgp_speaker.add_network(public_network_id)
        router = objects.RouterTestObj(self.neutron, self.nb_api)
        self.addCleanup(router.close)
        router_id = router.create()
        self.neutron.add_interface_router(
            router_id, body={'subnet_id': private_sn_id})
        self.neutron.add_gateway_router(
            router_id, body={'network_id': public_network_id})
        # Finnally, verify the route has been set in nb db.
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        self.assertEqual(1, len(nb_bgp_speaker.prefix_routes))

        vm = objects.VMTestObj(self, self.neutron)
        self.addCleanup(vm.close)
        vm_id = vm.create(network=private_network)
        vm_port = self.neutron.list_ports(device_id=vm_id).get('ports')[0]
        vm_port_id = vm_port.get('id')
        fip = objects.FloatingipTestObj(self.neutron, self.nb_api)
        self.addCleanup(fip.close)
        fip.create({'floating_network_id': public_network_id,
                    'port_id': vm_port_id})
        fip_addr = fip.get_floatingip().floating_ip_address
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        self.assertEqual(1, len(nb_bgp_speaker.host_routes))
        self.assertIn(
            host_route.HostRoute(destination=netaddr.IPNetwork(fip_addr),
                                 nexthop='172.24.4.100'),
            nb_bgp_speaker.host_routes)

        fip.update({'port_id': None})
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        self.assertFalse(nb_bgp_speaker.host_routes)

        bgp_speaker.remove_network(public_network_id)
        nb_bgp_speaker = bgp_speaker.get_nb_bgp_speaker()
        self.assertFalse(nb_bgp_speaker.prefix_routes)
