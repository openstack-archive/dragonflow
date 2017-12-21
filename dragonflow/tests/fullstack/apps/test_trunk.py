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

import netaddr
import time

from neutron_lib.api.definitions import allowedaddresspairs as aap
from neutron_lib import constants as n_const
from oslo_log import log
import ryu.lib.packet
import testscenarios

from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)

load_tests = testscenarios.load_tests_apply_scenarios


class TestTrunkApp(test_base.DFTestBase):
    def test_icmp_ping_pong(self):
        # Setup base components - two ports on 1 network
        self.topology = app_testing_objects.Topology(self.neutron, self.nb_api)
        self.addCleanup(self.topology.close)
        self.subnet1 = self.topology.create_subnet(cidr='192.168.12.0/24')
        self.port1 = self.subnet1.create_port()
        self.port2 = self.subnet1.create_port()
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # Setup VLAN ports
        self.network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(self.network.close)
        self.network.create()
        self.subnet = objects.SubnetTestObj(
                self.neutron, self.nb_api, network_id=self.network.network_id)
        self.addCleanup(self.subnet.close)
        self.subnet.create()
        self.vlan_port1 = objects.PortTestObj(
                self.neutron, self.nb_api, network_id=self.network.network_id)
        self.addCleanup(self.vlan_port1.close)
        self.vlan_port1.create()
        self.vlan_port2 = objects.PortTestObj(
                self.neutron, self.nb_api, network_id=self.network.network_id)
        self.addCleanup(self.vlan_port2.close)
        self.vlan_port2.create()

        self.cps1 = objects.ChildPortSegmentationTestObj(
                self.neutron, self.nb_api)
        self.addCleanup(self.cps1.close)
        self.cps1.create(
                self.port1.port.port_id, self.vlan_port1.port_id, 'vlan', 7)
        self.addCleanup(self.port1.unbind)

        self.cps2 = objects.ChildPortSegmentationTestObj(
                self.neutron, self.nb_api)
        self.addCleanup(self.cps2.close)
        self.cps2.create(
                self.port2.port.port_id, self.vlan_port2.port_id, 'vlan', 8)
        self.addCleanup(self.port2.unbind)

        # Setup policy
        ignore_action = app_testing_objects.IgnoreAction()
        key1 = (self.subnet1.subnet_id, self.port1.port_id)
        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, end simulation
                app_testing_objects.AndingFilter(
                        app_testing_objects.RyuVLANTagFilter(7),
                        app_testing_objects.RyuICMPPongFilter(self._get_ping)),
                actions=[app_testing_objects.DisableRuleAction(),
                         app_testing_objects.StopSimulationAction()]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.RyuARPGratuitousFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 packets
                app_testing_objects.RyuIPv6Filter(),
                actions=[
                    ignore_action
                ]
            ),
        ]
        key2 = (self.subnet1.subnet_id, self.port2.port_id)
        rules2 = [
            app_testing_objects.PortPolicyRule(
                # Detect ping, reply with pong
                app_testing_objects.AndingFilter(
                        app_testing_objects.RyuVLANTagFilter(8),
                        app_testing_objects.RyuICMPPingFilter()),
                actions=[app_testing_objects.SendAction(
                                self.subnet1.subnet_id,
                                self.port2.port_id,
                                self._create_pong_packet),
                         app_testing_objects.DisableRuleAction()]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.RyuARPGratuitousFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 packets
                app_testing_objects.RyuIPv6Filter(),
                actions=[
                    ignore_action
                ]
            ),
        ]
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        policy1 = app_testing_objects.PortPolicy(
            rules=rules1,
            default_action=raise_action
        )
        policy2 = app_testing_objects.PortPolicy(
            rules=rules2,
            default_action=raise_action
        )
        port_policies = {key1: policy1, key2: policy2}
        initial_packet = self._create_ping_packet()
        policy = app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        initial_packet,
                    ),
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction())
        self.addCleanup(policy.close)

        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # Verify port is up
        neutron_vlan_port1 = objects.get_port_by_id(self.neutron,
                                                    self.vlan_port1.port_id)
        self.assertEqual(n_const.PORT_STATUS_ACTIVE,
                         neutron_vlan_port1['status'])
        neutron_vlan_port2 = objects.get_port_by_id(self.neutron,
                                                    self.vlan_port2.port_id)
        self.assertEqual(n_const.PORT_STATUS_ACTIVE,
                         neutron_vlan_port2['status'])

        # Verify connectivity
        apps.start_policy(policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

    def _get_ping(self):
        return self._ping

    def _create_ping_packet(self, ttl=255):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=self.vlan_port1.get_logical_port().mac,
            dst=self.vlan_port2.get_logical_port().mac,
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_8021Q,
        )
        vlan = ryu.lib.packet.vlan.vlan(
            vid=7,
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=str(self.vlan_port1.get_logical_port().ip),
            dst=str(self.vlan_port2.get_logical_port().ip),
            ttl=ttl,
            proto=ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
        )
        ip_data = ryu.lib.packet.icmp.icmp(
            type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=ryu.lib.packet.icmp.echo(
                data=self._create_random_string())
        )
        self._ping = ip_data
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(vlan)
        result.add_protocol(ip)
        result.add_protocol(ip_data)
        result.serialize()
        return result.data

    def _create_pong_packet(self, buf):
        pkt = ryu.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
        vlan = pkt.get_protocol(ryu.lib.packet.vlan.vlan)
        ip = pkt.get_protocol(ryu.lib.packet.ipv4.ipv4)
        icmp = pkt.get_protocol(ryu.lib.packet.icmp.icmp)

        ether.src, ether.dst = ether.dst, ether.src
        self.assertEqual(
            ether.src,
            str(self.vlan_port2.get_logical_port().mac)
        )
        self.assertEqual(
            ether.dst,
            str(self.vlan_port1.get_logical_port().mac)
        )

        ip.src, ip.dst = ip.dst, ip.src
        self.assertEqual(
            netaddr.IPAddress(ip.src),
            self.vlan_port2.get_logical_port().ip
        )
        self.assertEqual(
            netaddr.IPAddress(ip.dst),
            self.vlan_port1.get_logical_port().ip
        )
        self.assertEqual(
            8,
            vlan.vid
        )

        icmp.type = ryu.lib.packet.icmp.ICMP_ECHO_REPLY
        icmp.csum = 0
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ether)
        result.add_protocol(vlan)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result.data


class TestNestedPortsApp(test_base.DFTestBase):

    scenarios = testscenarios.scenarios.multiply_scenarios(
        [
            ('ipv4', {'ip_ver': 4,
                      'cidr_outer': '192.168.12.0/24',
                      'cidr_inner': '192.168.13.0/24'}),
            ('ipv6', {'ip_ver': 6,
                      'cidr_outer': '1111:1111:1111::/64',
                      'cidr_inner': '1111:1111:1112::/64'}),
        ], [
            ('ipvlan', {'is_macvlan': False}),
            ('macvlan', {'is_macvlan': True}),
        ]
    )

    def test_icmp_ping_pong(self):
        # Setup base components - two ports on 1 network
        self.topology = app_testing_objects.Topology(self.neutron, self.nb_api)
        self.addCleanup(self.topology.close)
        self.subnet1 = self.topology.create_subnet(cidr=self.cidr_outer)
        self.port1 = self.subnet1.create_port()
        self.port2 = self.subnet1.create_port()
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # Setup MACVLAN ports
        self.network = objects.NetworkTestObj(self.neutron, self.nb_api)
        self.addCleanup(self.network.close)
        self.network.create()
        self.subnet = objects.SubnetTestObj(
                self.neutron, self.nb_api, network_id=self.network.network_id)
        self.addCleanup(self.subnet.close)
        self.subnet.create(subnet={
            'ip_version': self.ip_ver,
            'cidr': self.cidr_inner,
            'network_id': self.network.network_id
        })
        self.vlan_port1 = objects.PortTestObj(
                self.neutron, self.nb_api, network_id=self.network.network_id)
        self.addCleanup(self.vlan_port1.close)
        self.vlan_port1.create()
        self.vlan_port2 = objects.PortTestObj(
                self.neutron, self.nb_api, network_id=self.network.network_id)
        self.addCleanup(self.vlan_port2.close)
        self.vlan_port2.create()

        vlan_port1_lport = self.vlan_port1.get_logical_port()
        aap1 = {'ip_address': vlan_port1_lport.ip}
        if self.is_macvlan:
            aap1['mac_address'] = vlan_port1_lport.mac
        self.port1.port.update({aap.ADDRESS_PAIRS: [aap1]})

        vlan_port2_lport = self.vlan_port2.get_logical_port()
        aap2 = {'ip_address': vlan_port2_lport.ip}
        if self.is_macvlan:
            aap2['mac_address'] = vlan_port2_lport.mac
        self.port2.port.update({aap.ADDRESS_PAIRS: [aap2]})

        # Setup policy
        if self.ip_ver == 4:
            ethertype = n_const.IPv4
        elif self.ip_ver == 6:
            ethertype = n_const.IPv6
        ignore_action = app_testing_objects.IgnoreAction()
        key1 = (self.subnet1.subnet_id, self.port1.port_id)
        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, end simulation
                app_testing_objects.RyuICMPPongFilter(self._get_ping,
                                                      ethertype),
                actions=[app_testing_objects.DisableRuleAction(),
                         app_testing_objects.StopSimulationAction()]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore ARP request packets
                app_testing_objects.RyuARPRequestFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.RyuARPGratuitousFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 packets
                app_testing_objects.RyuIPv6Filter(),
                actions=[
                    ignore_action
                ]
            ),
        ]
        key2 = (self.subnet1.subnet_id, self.port2.port_id)
        rules2 = [
            app_testing_objects.PortPolicyRule(
                # Detect ping, reply with pong
                app_testing_objects.RyuICMPPingFilter(ethertype=ethertype),
                actions=[app_testing_objects.SendAction(
                                self.subnet1.subnet_id,
                                self.port2.port_id,
                                self._create_pong_packet),
                         app_testing_objects.DisableRuleAction()]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore ARP request packets
                app_testing_objects.RyuARPRequestFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.RyuARPGratuitousFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 packets
                app_testing_objects.RyuIPv6Filter(),
                actions=[
                    ignore_action
                ]
            ),
        ]
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        policy1 = app_testing_objects.PortPolicy(
            rules=rules1,
            default_action=raise_action
        )
        policy2 = app_testing_objects.PortPolicy(
            rules=rules2,
            default_action=raise_action
        )
        port_policies = {key1: policy1, key2: policy2}
        initial_packet = self._create_ping_packet()
        policy = app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        initial_packet,
                    ),
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction())
        self.addCleanup(policy.close)

        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # Verify port is up
        neutron_vlan_port1 = objects.get_port_by_id(self.neutron,
                                                    self.vlan_port1.port_id)
        self.assertEqual(n_const.PORT_STATUS_ACTIVE,
                         neutron_vlan_port1['status'])
        neutron_vlan_port2 = objects.get_port_by_id(self.neutron,
                                                    self.vlan_port2.port_id)
        self.assertEqual(n_const.PORT_STATUS_ACTIVE,
                         neutron_vlan_port2['status'])

        # Verify connectivity
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def _get_ping(self):
        return self._ping

    def _create_ping_packet(self, ttl=255):
        if self.is_macvlan:
            src_mac = self.vlan_port1.get_logical_port().mac
        else:  # ipvlan
            src_mac = self.port1.port.get_logical_port().mac
        dst_mac = self.vlan_port2.get_logical_port().mac
        icmp_data = self._create_random_string()
        if self.ip_ver == 4:
            ethernet = ryu.lib.packet.ethernet.ethernet(
                src=src_mac,
                dst=dst_mac,
                ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
            )
            ip = ryu.lib.packet.ipv4.ipv4(
                src=str(self.vlan_port1.get_logical_port().ip),
                dst=str(self.vlan_port2.get_logical_port().ip),
                ttl=ttl,
                proto=ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
            )
            ip_data = ryu.lib.packet.icmp.icmp(
                type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
                data=ryu.lib.packet.icmp.echo(
                    data=icmp_data)
            )
        elif self.ip_ver == 6:
            ethernet = ryu.lib.packet.ethernet.ethernet(
                src=src_mac,
                dst=dst_mac,
                ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IPV6,
            )
            ip = ryu.lib.packet.ipv6.ipv6(
                src=str(self.vlan_port1.get_logical_port().ip),
                dst=str(self.vlan_port2.get_logical_port().ip),
                hop_limit=ttl,
                nxt=ryu.lib.packet.ipv6.inet.IPPROTO_ICMPV6,
            )
            ip_data = ryu.lib.packet.icmpv6.icmpv6(
                type_=ryu.lib.packet.icmpv6.ICMPV6_ECHO_REQUEST,
                data=ryu.lib.packet.icmpv6.echo(data=icmp_data)
            )
        self._ping = ip_data
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(ip_data)
        result.serialize()
        return result.data

    def _create_pong_packet(self, buf):
        pkt = ryu.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
        if self.ip_ver == 4:
            ip = pkt.get_protocol(ryu.lib.packet.ipv4.ipv4)
            icmp = pkt.get_protocol(ryu.lib.packet.icmp.icmp)
            icmp_reply_type = ryu.lib.packet.icmp.ICMP_ECHO_REPLY
        elif self.ip_ver == 6:
            ip = pkt.get_protocol(ryu.lib.packet.ipv6.ipv6)
            icmp = pkt.get_protocol(ryu.lib.packet.icmpv6.icmpv6)
            icmp_reply_type = ryu.lib.packet.icmpv6.ICMPV6_ECHO_REPLY

        if self.is_macvlan:
            expected_src_mac = str(self.vlan_port2.get_logical_port().mac)
        else:  # ipvlan
            expected_src_mac = str(self.port2.port.get_logical_port().mac)
        expected_dst_mac = str(self.vlan_port1.get_logical_port().mac)
        ether.src, ether.dst = ether.dst, ether.src
        self.assertEqual(
            ether.src,
            expected_src_mac
        )
        self.assertEqual(
            ether.dst,
            expected_dst_mac
        )

        ip.src, ip.dst = ip.dst, ip.src
        self.assertEqual(
            netaddr.IPAddress(ip.src),
            self.vlan_port2.get_logical_port().ip
        )
        self.assertEqual(
            netaddr.IPAddress(ip.dst),
            self.vlan_port1.get_logical_port().ip
        )

        if self.ip_ver == 4:
            icmp.type = icmp_reply_type
        elif self.ip_ver == 6:
            icmp.type_ = icmp_reply_type
        icmp.csum = 0
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ether)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result.data
