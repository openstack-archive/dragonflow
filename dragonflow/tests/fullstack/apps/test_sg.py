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

from neutron_lib import constants as n_const
from oslo_log import log
import ryu.lib.packet

from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.common import utils as test_utils
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


class TestSGApp(test_base.DFTestBase):
    def setUp(self):
        super(TestSGApp, self).setUp()
        self.topology = None
        self.policy = None
        try:
            self.security_group = self.store(objects.SecGroupTestObj(
                self.neutron,
                self.nb_api))
            security_group_id = self.security_group.create()
            self.assertTrue(self.security_group.exists())

            self.security_group2 = self.store(objects.SecGroupTestObj(
                self.neutron,
                self.nb_api))
            security_group_id2 = self.security_group2.create()
            self.assertTrue(self.security_group2.exists())

            self.security_group3 = self.store(objects.SecGroupTestObj(
                self.neutron,
                self.nb_api))
            security_group_id3 = self.security_group3.create()
            self.assertTrue(self.security_group3.exists())

            self.topology = self.store(
                app_testing_objects.Topology(
                    self.neutron,
                    self.nb_api
                )
            )

            self.active_security_group_id = security_group_id
            self.inactive_security_group_id = security_group_id2
            self.allowed_address_pairs_security_group_id = security_group_id3

            self.permit_icmp_request = self._get_icmp_request1
            self.no_permit_icmp_request = self._get_icmp_request2

        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _setup_subnet(self, cidr):
        network = netaddr.IPNetwork(cidr)

        self.port1 = self.subnet.create_port()
        self.port2 = self.subnet.create_port()
        self.port3 = self.subnet.create_port([self.active_security_group_id])
        self.port4 = self.subnet.create_port()

        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        self.port4.update(
            {'allowed_address_pairs': [{'ip_address': network[100]}]})

        port1_lport = self.port1.port.get_logical_port()
        self.assertIsNotNone(port1_lport)

        port2_lport = self.port2.port.get_logical_port()
        self.assertIsNotNone(port2_lport)

    def _setup_groups_rules(self, cidr):
        if self.ethertype == n_const.IPv4:
            icmp_type = n_const.PROTO_NAME_ICMP
        else:
            icmp_type = n_const.PROTO_NAME_IPV6_ICMP_LEGACY
        egress_rule_info = {'ethertype': self.ethertype,
                            'direction': 'egress',
                            'protocol': icmp_type}
        egress_rule_id = self.security_group.rule_create(
            secrule=egress_rule_info)
        self.assertTrue(self.security_group.rule_exists(egress_rule_id))
        egress_rule_id2 = self.security_group2.rule_create(
            secrule=egress_rule_info)
        self.assertTrue(self.security_group2.rule_exists(egress_rule_id2))

        # Get lports
        port1_lport = self.port1.port.get_logical_port()
        port1_fixed_ip = port1_lport.ip
        port2_lport = self.port2.port.get_logical_port()
        port2_fixed_ip = port2_lport.ip
        ingress_rule_info = {
            'ethertype': self.ethertype,
            'direction': 'ingress',
            'protocol': icmp_type,
            'remote_ip_prefix': str(netaddr.IPNetwork(port1_fixed_ip))}
        ingress_rule_id = self.security_group.rule_create(
            secrule=ingress_rule_info)
        self.assertTrue(self.security_group.rule_exists(ingress_rule_id))

        ingress_rule_info2 = {
            'ethertype': self.ethertype,
            'direction': 'ingress',
            'protocol': icmp_type,
            'remote_ip_prefix': str(netaddr.IPNetwork(port2_fixed_ip))}
        ingress_rule_id2 = self.security_group2.rule_create(
            secrule=ingress_rule_info2)
        self.assertTrue(self.security_group2.rule_exists(ingress_rule_id2))

        ingress_rule_info3 = {
            'ethertype': self.ethertype,
            'direction': 'ingress',
            'protocol': icmp_type,
            'remote_group_id':
                self.topology.fake_default_security_group.secgroup_id}
        ingress_rule_id3 = self.security_group3.rule_create(
            secrule=ingress_rule_info3)
        self.assertTrue(self.security_group3.rule_exists(ingress_rule_id3))

        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

    def _update_policy(self):
        packet1, self.icmp_request1 = \
            self._create_ping_packet(self.port1, self.port3)
        packet2, self.icmp_request2 = \
            self._create_ping_packet(self.port2, self.port3)

        port_policies = self._create_port_policies()

        self.policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.port1.port_id,
                        packet1.data,
                    ),
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.port2.port_id,
                        packet2.data,
                    )
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )

    def _create_allowed_address_pairs_policy(self):
        packet1, self.allowed_address_pairs_icmp_request = \
            self._create_ping_packet(self.port4, self.port3)

        port_policies = self._create_allowed_address_pairs_port_policies()

        self.allowed_address_pairs_policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.port4.port_id,
                        packet1.data,
                    )
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )

    def _get_icmp_request1(self):
        return self.icmp_request1

    def _get_icmp_request2(self):
        return self.icmp_request2

    def _get_allowed_address_pairs_icmp_request(self):
        return self.allowed_address_pairs_icmp_request

    def _get_filtering_rules(self):
        ignore_action = app_testing_objects.IgnoreAction()
        rules = [
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
            )
        ]
        return rules

    def _create_port_policies(self):
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        key1 = (self.subnet.subnet_id, self.permit_port.port_id)
        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, end simulation
                app_testing_objects.RyuICMPPongFilter(
                    self.permit_icmp_request, ethertype=self.ethertype),
                actions=[
                    app_testing_objects.DisableRuleAction(),
                    app_testing_objects.StopSimulationAction(),
                ]
            ),
        ]
        key2 = (self.subnet.subnet_id, self.no_permit_port.port_id)
        rules2 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, raise unexpected packet exception
                app_testing_objects.RyuICMPPongFilter(
                    self.no_permit_icmp_request,
                    self.ethertype),
                actions=[
                    raise_action
                ]
            ),
        ]
        key3 = (self.subnet.subnet_id, self.port3.port_id)
        rules3 = [
            app_testing_objects.PortPolicyRule(
                # Detect ping from port1, reply with pong
                app_testing_objects.RyuICMPPingFilter(
                    self.permit_icmp_request,
                    self.ethertype),
                actions=[
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.port3.port_id,
                        self._create_pong_packet
                    ),
                    app_testing_objects.DisableRuleAction(),
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Detect ping from port2, raise unexpected packet exception
                app_testing_objects.RyuICMPPingFilter(
                    self.no_permit_icmp_request,
                    self.ethertype),
                actions=[
                    raise_action
                ]
            )
        ]
        filtering_rules = self._get_filtering_rules()
        rules1 += filtering_rules
        rules3 += filtering_rules
        rules2 += filtering_rules

        policy1 = app_testing_objects.PortPolicy(
            rules=rules1,
            default_action=raise_action
        )
        policy2 = app_testing_objects.PortPolicy(
            rules=rules2,
            default_action=raise_action
        )
        policy3 = app_testing_objects.PortPolicy(
            rules=rules3,
            default_action=raise_action
        )
        return {
            key1: policy1,
            key2: policy2,
            key3: policy3
        }

    def _create_allowed_address_pairs_port_policies(self):
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        key = (self.subnet.subnet_id, self.port3.port_id)
        rules = [
            app_testing_objects.PortPolicyRule(
                # Detect ping from port4, end the test
                app_testing_objects.RyuICMPPingFilter(
                    self._get_allowed_address_pairs_icmp_request,
                    self.ethertype),
                actions=[
                    app_testing_objects.DisableRuleAction(),
                    app_testing_objects.StopSimulationAction()
                ]
            ),
        ]
        filtering_rules = self._get_filtering_rules()
        rules += filtering_rules
        policy1 = app_testing_objects.PortPolicy(
            rules=rules,
            default_action=raise_action
        )
        return {
            key: policy1,
        }

    def _create_packet_protocol(self, src_ip, dst_ip):
        if self.ethertype == n_const.IPv4:
            ip = ryu.lib.packet.ipv4.ipv4(
                src=str(src_ip),
                dst=str(dst_ip),
                proto=self.icmp_type
            )
        else:
            ip = ryu.lib.packet.ipv6.ipv6(
                src=str(src_ip),
                dst=str(dst_ip),
                nxt=self.icmp_type)
        return ip

    def _create_ping_packet(self, src_port, dst_port):
        src_mac, src_ip = apps.get_port_mac_and_ip(src_port)

        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=str(src_mac),
            dst=str(dst_port.port.get_logical_port().mac),
            ethertype=self.ethtype,
        )
        dst_ip = dst_port.port.get_logical_port().ip
        ip = self._create_packet_protocol(src_ip, dst_ip)

        icmp_id = int(time.mktime(time.gmtime())) & 0xffff
        icmp_seq = 0
        icmp = self.icmp_class(
            type_=self.icmp_echo_request,
            data=self.icmp_echo_class(id_=icmp_id,
                                      seq=icmp_seq,
                                      data=self._create_random_string())
        )
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result, icmp

    def _create_pong_packet(self, buf):
        pkt = ryu.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
        ip = pkt.get_protocol(self.ip_class)
        icmp = pkt.get_protocol(self.icmp_class)

        src_mac, src_ip = apps.get_port_mac_and_ip(self.permit_port)

        self.assertEqual(
            ether.src,
            src_mac
        )
        self.assertEqual(
            ether.dst,
            self.port3.port.get_logical_port().mac
        )

        self.assertEqual(
            netaddr.IPAddress(ip.src),
            src_ip
        )
        self.assertEqual(
            netaddr.IPAddress(ip.dst),
            self.port3.port.get_logical_port().ip
        )
        ether.src, ether.dst = ether.dst, ether.src
        ip.src, ip.dst = ip.dst, ip.src

        if self.ethertype == n_const.IPv4:
            icmp.type = self.icmp_echo_reply
        else:
            icmp.type_ = self.icmp_echo_reply
        icmp.csum = 0
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ether)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result.data

    def _switch_to_another_security_group(self):
        try:
            self.active_security_group_id, self.inactive_security_group_id = \
                self.inactive_security_group_id, self.active_security_group_id
            self.permit_port, self.no_permit_port = \
                self.no_permit_port, self.permit_port
            self.permit_icmp_request, self.no_permit_icmp_request = \
                self.no_permit_icmp_request, self.permit_icmp_request

            self.port3.update(
                {"security_groups": [self.active_security_group_id]})

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

            self._update_policy()

        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _icmp_ping_pong(self):
        # the rules of the initial security group associated with port3
        # only let icmp echo requests from port1 pass.

        self._update_policy()
        self._create_allowed_address_pairs_policy()
        apps.start_policy(self.policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # switch the associated security group with port3 to a new security
        # group, and rules of this security group only let icmp echo requests
        # from port2 pass.
        self._switch_to_another_security_group()
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        apps.start_policy(self.policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # switch the associated security group with port3 to the initial
        # security group
        self._switch_to_another_security_group()
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        apps.start_policy(self.policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

        ovs = test_utils.OvsFlowsParser()
        LOG.info("flows are: %s",
                 ovs.get_ovs_flows(self.integration_bridge))

        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]

        self.port3.update({"security_groups": [
            self.allowed_address_pairs_security_group_id]})
        time.sleep(const.DEFAULT_CMD_TIMEOUT)
        self.allowed_address_pairs_policy.start(self.topology)
        self.allowed_address_pairs_policy.wait(30)

        if len(self.allowed_address_pairs_policy.exceptions) > 0:
            raise self.allowed_address_pairs_policy.exceptions[0]


class TestSGAppIpv4(TestSGApp):
    def setUp(self):
        super(TestSGAppIpv4, self).setUp()
        try:
            # Add IPv4 Network
            self.ethertype = n_const.IPv4
            cidr_ipv4 = '192.168.14.0/24'
            self.subnet = self.topology.create_subnet(cidr=cidr_ipv4)
            self._setup_subnet(cidr=cidr_ipv4)

            # Add IPv4 group rules
            self._setup_groups_rules(cidr=cidr_ipv4)

            # the rules of the initial security group associated with port3
            self.permit_port = self.port1
            self.no_permit_port = self.port2

            self.ip_class = ryu.lib.packet.ipv4.ipv4
            self.icmp_class = ryu.lib.packet.icmp.icmp
            self.icmp_echo_class = ryu.lib.packet.icmp.echo
            self.icmp_type = ryu.lib.packet.ipv4.inet.IPPROTO_ICMP
            self.icmp_echo_request = ryu.lib.packet.icmp.ICMP_ECHO_REQUEST
            self.icmp_echo_reply = ryu.lib.packet.icmp.ICMP_ECHO_REPLY
            self.ethtype = ryu.lib.packet.ethernet.ether.ETH_TYPE_IP

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def test_icmp_ping_pong(self):
        self._icmp_ping_pong()


class TestSGAppIpv6(TestSGApp):
    def setUp(self):
        super(TestSGAppIpv6, self).setUp()
        try:
            # Add IPv6 nodes
            cidr_ipv6 = '1111::/64'
            self.ethertype = n_const.IPv6
            self.subnet = self.topology.create_subnet(cidr=cidr_ipv6)
            self._setup_subnet(cidr=cidr_ipv6)

            # Add IPv6 group rules
            self._setup_groups_rules(cidr=cidr_ipv6)

            # the rules of the initial security group associated with port3
            self.permit_port = self.port1
            self.no_permit_port = self.port2

            self.ip_class = ryu.lib.packet.ipv6.ipv6
            self.icmp_class = ryu.lib.packet.icmpv6.icmpv6
            self.icmp_echo_class = ryu.lib.packet.icmpv6.echo
            self.icmp_type = ryu.lib.packet.ipv6.inet.IPPROTO_ICMPV6
            self.icmp_echo_request = ryu.lib.packet.icmpv6.ICMPV6_ECHO_REQUEST
            self.icmp_echo_reply = ryu.lib.packet.icmpv6.ICMPV6_ECHO_REPLY
            self.ethtype = ryu.lib.packet.ethernet.ether.ETH_TYPE_IPV6
            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _get_filtering_rules(self):
        ignore_action = app_testing_objects.IgnoreAction()
        rules = [
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.RyuARPGratuitousFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore Neighbor Advertisements
                app_testing_objects.RyuNeighborSolicitationFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore Neighbor Advertisements
                app_testing_objects.RyuNeighborAdvertisementFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore Neighbor Advertisements
                app_testing_objects.RyuRouterSolicitationFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 multicast
                app_testing_objects.RyuIpv6MulticastFilter(),
                actions=[
                    ignore_action
                ]
            )
        ]
        return rules

    def test_icmp_ping_pong(self):
        self._icmp_ping_pong()
