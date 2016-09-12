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

import random
import string
import sys
import time

from neutron.agent.linux.utils import wait_until_true
from oslo_log import log
import ryu.lib.packet

from dragonflow._i18n import _LI
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import utils as test_utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


class TestApps(test_base.DFTestBase):
    def test_infrastructure(self):
        try:
            topology = app_testing_objects.Topology(self.neutron, self.nb_api)
            subnet1 = topology.create_subnet(cidr='192.168.10.0/24')
            subnet2 = topology.create_subnet(cidr='192.168.11.0/24')
            port1 = subnet1.create_port()
            port2 = subnet2.create_port()
            topology.create_router([subnet1.subnet_id, subnet2.subnet_id])
            LOG.info(_LI('Port1 name: {}').format(port1.tap.tap.name))
            LOG.info(_LI('Port2 name: {}').format(port2.tap.tap.name))
            test_utils.print_command(['ip', 'addr'])
            test_utils.print_command(['ovs-vsctl', 'show'], True)
            test_utils.print_command(
                ['ovs-ofctl', 'show', self.integration_bridge],
                True
            )
            test_utils.print_command(
                ['ovs-ofctl', 'dump-flows', self.integration_bridge],
                True
            )
            test_utils.print_command(
                ['ovsdb-client', 'dump', 'Open_vSwitch'],
                True
            )
        except Exception as e:
            traceback = sys.exc_info()[2]
            try:
                topology.close()
            except Exception:
                pass  # Ignore
            # Just calling raise may raise an exception from topology.close()
            raise e, None, traceback
        topology.close()


class TestArpResponder(test_base.DFTestBase):

    def setUp(self):
        super(TestArpResponder, self).setUp()
        self.topology = None
        self.policy = None
        try:
            self.topology = app_testing_objects.Topology(
                self.neutron,
                self.nb_api)
            subnet1 = self.topology.create_subnet(cidr='192.168.10.0/24')
            port1 = subnet1.create_port()
            port2 = subnet1.create_port()
            time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
            # Create policy
            arp_packet = self._create_arp_request(
                src_port=port1.port.get_logical_port(),
                dst_port=port2.port.get_logical_port(),
            )
            send_arp_request = app_testing_objects.SendAction(
                subnet1.subnet_id,
                port1.port_id,
                str(arp_packet)
            )
            ignore_action = app_testing_objects.IgnoreAction()
            log_action = app_testing_objects.LogAction()
            key1 = (subnet1.subnet_id, port1.port_id)
            port_policies = {
                key1: app_testing_objects.PortPolicy(
                    rules=[
                        app_testing_objects.PortPolicyRule(
                            # Detect arp replies
                            app_testing_objects.RyuARPReplyFilter(),
                            actions=[
                                log_action,
                                app_testing_objects.StopSimulationAction()
                            ]
                        ),
                        app_testing_objects.PortPolicyRule(
                            # Ignore IPv6 packets
                            app_testing_objects.RyuIPv6Filter(),
                            actions=[
                                ignore_action
                            ]
                        ),
                    ],
                    default_action=app_testing_objects.RaiseAction(
                        "Unexpected packet"
                    )
                ),
            }
            self.policy = app_testing_objects.Policy(
                initial_actions=[send_arp_request],
                port_policies=port_policies,
                unknown_port_action=ignore_action
            )
        except Exception:
            if self.topology:
                self.topology.close()
            raise
        self.store(self.topology)
        self.store(self.policy)

    def _create_arp_request(self, src_port, dst_port):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=src_port.get_mac(),
            dst="ff:ff:ff:ff:ff:ff",
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_ARP,
        )
        arp = ryu.lib.packet.arp.arp_ip(
            opcode=1,
            src_mac=src_port.get_mac(), src_ip=src_port.get_ip(),
            dst_mac='00:00:00:00:00:00', dst_ip=dst_port.get_ip(),
        )
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(arp)
        result.serialize()
        return result.data

    def tearDown(self):
        super(TestArpResponder, self).tearDown()
        self.policy.close()
        self.topology.close()

    def test_simple_response(self):
        """
        2 ports on 1 subnet. 1 port asks for MAC of other.
        Policy:
            port1:
                Send ARP request
                Receive ARP response
            port2:
                Do nothing
        """
        self.policy.start(self.topology)
        self.policy.wait(30)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]


class TestDHCPApp(test_base.DFTestBase):

    def setUp(self):
        super(TestDHCPApp, self).setUp()
        self.topology = None
        self.policy = None
        try:
            self.topology = self.store(
                app_testing_objects.Topology(
                    self.neutron,
                    self.nb_api
                )
            )
            self.subnet1 = self.topology.create_subnet(cidr='192.168.11.0/24')
            self.port1 = self.subnet1.create_port()
            self.port2 = self.subnet1.create_port()
            time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
            # Create policy
            dhcp_packet = self._create_dhcp_discover()
            send_dhcp_offer = app_testing_objects.SendAction(
                self.subnet1.subnet_id,
                self.port1.port_id,
                str(dhcp_packet)
            )
            port_policies = self._create_port_policies()
            self.policy = self.store(
                app_testing_objects.Policy(
                    initial_actions=[send_dhcp_offer],
                    port_policies=port_policies,
                    unknown_port_action=app_testing_objects.IgnoreAction()
                )
            )
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _create_udp_packet_for_dhcp(self,
            dst_mac="ff:ff:ff:ff:ff:ff",
            src_ip='0.0.0.0',
            dst_ip='255.255.255.255'):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=self.port1.port.get_logical_port().get_mac(),
            dst=dst_mac,
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=src_ip,
            dst=dst_ip,
            proto=ryu.lib.packet.ipv4.inet.IPPROTO_UDP,
        )
        udp = ryu.lib.packet.udp.udp(
            src_port=68,
            dst_port=67,
        )
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(udp)
        return result

    def _create_dhcp_discover(self):
        result = self._create_udp_packet_for_dhcp()
        options = [
            ryu.lib.packet.dhcp.option(
                ryu.lib.packet.dhcp.DHCP_MESSAGE_TYPE_OPT,
                chr(ryu.lib.packet.dhcp.DHCP_DISCOVER),
            ),
            ryu.lib.packet.dhcp.option(
                ryu.lib.packet.dhcp.DHCP_PARAMETER_REQUEST_LIST_OPT,
                chr(ryu.lib.packet.dhcp.DHCP_GATEWAY_ADDR_OPT),
            ),
        ]
        dhcp = ryu.lib.packet.dhcp.dhcp(
            op=1,
            chaddr=self.port1.port.get_logical_port().get_mac(),
            options=ryu.lib.packet.dhcp.options(option_list=options),
        )
        result.add_protocol(dhcp)
        result.serialize()
        return result.data

    def _create_dhcp_request(self, offer_buf, is_renewal=False):
        def is_121_exist(offer):
            for option in offer.options.option_list:
                if option.tag is 121:
                    return True
            return False

        pkt = ryu.lib.packet.packet.Packet(offer_buf)
        offer = pkt.get_protocol(ryu.lib.packet.dhcp.dhcp)
        self.assertEqual(
            self.port1.port.get_logical_port().get_ip(),
            offer.yiaddr
        )
        self.assertTrue(is_121_exist(offer))
        if is_renewal:
            ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
            ip = pkt.get_protocol(ryu.lib.packet.ipv4.ipv4)
            dst_mac = ether.src
            dst_ip = ip.src
            src_ip = self.port1.port.get_logical_port().get_ip()
            result = self._create_udp_packet_for_dhcp(
                dst_mac=dst_mac,
                src_ip=src_ip,
                dst_ip=dst_ip
            )
        else:
            result = self._create_udp_packet_for_dhcp()
        options = [
            ryu.lib.packet.dhcp.option(
                ryu.lib.packet.dhcp.DHCP_MESSAGE_TYPE_OPT,
                chr(ryu.lib.packet.dhcp.DHCP_REQUEST),
            ),
            ryu.lib.packet.dhcp.option(
                ryu.lib.packet.dhcp.DHCP_REQUESTED_IP_ADDR_OPT,
                offer.yiaddr,
            ),
            ryu.lib.packet.dhcp.option(
                ryu.lib.packet.dhcp.DHCP_PARAMETER_REQUEST_LIST_OPT,
                chr(ryu.lib.packet.dhcp.DHCP_GATEWAY_ADDR_OPT),
            ),
        ]
        dhcp = ryu.lib.packet.dhcp.dhcp(
            op=1,
            chaddr=self.port1.port.get_logical_port().get_mac(),
            xid=offer.xid,
            options=ryu.lib.packet.dhcp.options(option_list=options),
        )
        result.add_protocol(dhcp)
        result.serialize()
        return result.data

    def _create_dhcp_renewal_request(self, offer_buf):
        return self._create_dhcp_request(offer_buf, is_renewal=True)

    def _create_port_policies(self, disable_rule=True):
        ignore_action = app_testing_objects.IgnoreAction()
        key1 = (self.subnet1.subnet_id, self.port1.port_id)
        actions = [
                app_testing_objects.SendAction(
                    self.subnet1.subnet_id,
                    self.port1.port_id,
                    self._create_dhcp_request
                )]
        if disable_rule:
            actions.append(app_testing_objects.DisableRuleAction())

        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect dhcp offer
                app_testing_objects.RyuDHCPOfferFilter(),
                actions
            ),
            app_testing_objects.PortPolicyRule(
                # Detect dhcp acknowledge
                app_testing_objects.RyuDHCPAckFilter(),
                actions=[
                    app_testing_objects.DisableRuleAction(),
                    app_testing_objects.WaitAction(5),
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        self._create_dhcp_renewal_request
                    ),
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Detect dhcp acknowledge
                app_testing_objects.RyuDHCPAckFilter(),
                actions=[
                    app_testing_objects.StopSimulationAction(),
                    app_testing_objects.DisableRuleAction()
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
                # Detect arp replies
                app_testing_objects.RyuDHCPFilter(),
                actions=[
                    app_testing_objects.RaiseAction(
                        "Received DHCP packet"
                    )
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
        return {
            key1: policy1,
            key2: policy2,
        }

    def test_dhcp_app(self):
        self.policy.start(self.topology)
        self.policy.wait(30)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]

    def _check_dhcp_block_rule(self, flows, ofport=None):
        for flow in flows:
            if flow['table'] == '11' and 'drop' in flow['actions']:
                if ofport is None or 'inport=' + ofport in flow['match']:
                    return True
        return False

    def test_dhcp_app_dos_block(self):
        def internal_predicate():
            ovs = test_utils.OvsFlowsParser()
            return (self._check_dhcp_block_rule(
                ovs.dump(self.integration_bridge)))

        dhcp_packet = self._create_dhcp_discover()
        send_dhcp_offer = app_testing_objects.SendAction(
            self.subnet1.subnet_id,
            self.port1.port_id,
            str(dhcp_packet)
        )

        port_policies = self._create_port_policies(disable_rule=False)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[send_dhcp_offer,
                                send_dhcp_offer,
                                send_dhcp_offer,
                                send_dhcp_offer],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )

        policy.start(self.topology)
        wait_until_true(internal_predicate, 30, 1, None)


class TestL3App(test_base.DFTestBase):
    def setUp(self):
        super(TestL3App, self).setUp()
        self.topology = None
        self.policy = None
        self._ping = None
        try:
            self.topology = self.store(
                app_testing_objects.Topology(
                    self.neutron,
                    self.nb_api
                )
            )
            self.subnet1 = self.topology.create_subnet(cidr='192.168.12.0/24')
            self.subnet2 = self.topology.create_subnet(cidr='192.168.13.0/24')
            self.port1 = self.subnet1.create_port()
            self.port2 = self.subnet2.create_port()
            self.router = self.topology.create_router([
                self.subnet1.subnet_id,
                self.subnet2.subnet_id,
            ])
            time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)

            port_policies = self._create_port_policies()
            self.policy = self.store(
                app_testing_objects.Policy(
                    initial_actions=[
                        app_testing_objects.SendAction(
                            self.subnet1.subnet_id,
                            self.port1.port_id,
                            self._create_ping_packet
                        ),
                    ],
                    port_policies=port_policies,
                    unknown_port_action=app_testing_objects.IgnoreAction()
                )
            )
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _create_port_policies(self):
        ignore_action = app_testing_objects.IgnoreAction()
        key1 = (self.subnet1.subnet_id, self.port1.port_id)
        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, end simulation
                app_testing_objects.RyuICMPPongFilter(self._get_ping),
                actions=[
                    app_testing_objects.DisableRuleAction(),
                    app_testing_objects.StopSimulationAction(),
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
        key2 = (self.subnet2.subnet_id, self.port2.port_id)
        rules2 = [
            app_testing_objects.PortPolicyRule(
                # Detect ping, reply with pong
                app_testing_objects.RyuICMPPingFilter(),
                actions=[
                    app_testing_objects.SendAction(
                        self.subnet2.subnet_id,
                        self.port2.port_id,
                        self._create_pong_packet
                    ),
                    app_testing_objects.DisableRuleAction(),
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
        return {
            key1: policy1,
            key2: policy2,
        }

    def _create_ping_packet(self, buf):
        router_interface = self.router.router_interfaces[
            self.subnet1.subnet_id
        ]
        router_interface_port = self.neutron.show_port(
            router_interface['port_id']
        )
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=self.port1.port.get_logical_port().get_mac(),
            dst=router_interface_port['port']['mac_address'],
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=self.port1.port.get_logical_port().get_ip(),
            dst=self.port2.port.get_logical_port().get_ip(),
            proto=ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
        )
        icmp = ryu.lib.packet.icmp.icmp(
            type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=ryu.lib.packet.icmp.echo(data=self._create_random_string())
        )
        self._ping = icmp
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result.data

    def _get_ping(self):
        return self._ping

    def _create_random_string(self, length=16):
        alphabet = string.printable
        return ''.join([random.choice(alphabet) for _ in range(length)])

    def _create_pong_packet(self, buf):
        pkt = ryu.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
        ip = pkt.get_protocol(ryu.lib.packet.ipv4.ipv4)
        icmp = pkt.get_protocol(ryu.lib.packet.icmp.icmp)

        src_mac = ether.dst
        dst_mac = ether.src
        ether.src = src_mac
        ether.dst = dst_mac
        self.assertEqual(
            src_mac,
            self.port2.port.get_logical_port().get_mac()
        )
        router_interface = self.router.router_interfaces[
            self.subnet2.subnet_id
        ]
        router_interface_port = self.neutron.show_port(
            router_interface['port_id']
        )
        router_mac = router_interface_port['port']['mac_address']
        self.assertEqual(
            dst_mac,
            router_mac,
        )

        src_ip = ip.dst
        dst_ip = ip.src
        ip.src = src_ip
        ip.dst = dst_ip
        self.assertEqual(
            src_ip,
            self.port2.port.get_logical_port().get_ip()
        )
        self.assertEqual(
            dst_ip,
            self.port1.port.get_logical_port().get_ip()
        )

        icmp.type = ryu.lib.packet.icmp.ICMP_ECHO_REPLY
        icmp.csum = 0
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ether)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result.data

    def test_icmp_ping_pong(self):
        self.policy.start(self.topology)
        self.policy.wait(30)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]


class TestSGApp(test_base.DFTestBase):
    def setUp(self):
        super(TestSGApp, self).setUp()
        self.topology = None
        self.policy = None
        try:
            security_group = self.store(objects.SecGroupTestObj(
                self.neutron,
                self.nb_api))
            security_group_id = security_group.create()
            self.assertTrue(security_group.exists())

            security_group2 = self.store(objects.SecGroupTestObj(
                self.neutron,
                self.nb_api))
            security_group_id2 = security_group2.create()
            self.assertTrue(security_group2.exists())

            self.topology = self.store(
                app_testing_objects.Topology(
                    self.neutron,
                    self.nb_api
                )
            )

            self.subnet = self.topology.create_subnet(cidr='192.168.14.0/24')
            self.port1 = self.subnet.create_port()
            self.port2 = self.subnet.create_port()
            self.port3 = self.subnet.create_port([security_group_id])

            port1_lport = self.port1.port.get_logical_port()
            self.assertIsNotNone(port1_lport)
            port1_fixed_ip = port1_lport.get_ip()

            port2_lport = self.port2.port.get_logical_port()
            self.assertIsNotNone(port2_lport)
            port2_fixed_ip = port2_lport.get_ip()

            egress_rule_info = {'ethertype': 'IPv4',
                                'direction': 'egress',
                                'protocol': 'icmp'}
            egress_rule_id = security_group.rule_create(
                secrule=egress_rule_info)
            self.assertTrue(security_group.rule_exists(egress_rule_id))
            egress_rule_id2 = security_group2.rule_create(
                secrule=egress_rule_info)
            self.assertTrue(security_group2.rule_exists(egress_rule_id2))

            ingress_rule_info = {'ethertype': 'IPv4',
                                 'direction': 'ingress',
                                 'protocol': 'icmp',
                                 'remote_ip_prefix': port1_fixed_ip + "/32"}
            ingress_rule_id = security_group.rule_create(
                secrule=ingress_rule_info)
            self.assertTrue(security_group.rule_exists(ingress_rule_id))

            ingress_rule_info2 = {'ethertype': 'IPv4',
                                  'direction': 'ingress',
                                  'protocol': 'icmp',
                                  'remote_ip_prefix': port2_fixed_ip + "/32"}
            ingress_rule_id2 = security_group2.rule_create(
                secrule=ingress_rule_info2)
            self.assertTrue(security_group2.rule_exists(ingress_rule_id2))

            self.active_security_group_id = security_group_id
            self.inactive_security_group_id = security_group_id2
            self.permit_port_id = self.port1.port_id
            self.no_permit_port_id = self.port2.port_id
            self.permit_icmp_request = self._get_icmp_request1
            self.no_permit_icmp_request = self._get_icmp_request2

            time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)

            self._update_policy()
        except Exception:
            if self.topology:
                self.topology.close()
            raise

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
                        str(packet1.data)
                    ),
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.port2.port_id,
                        str(packet2.data)
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

    def _create_port_policies(self):

        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        key1 = (self.subnet.subnet_id, self.permit_port_id)
        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, end simulation
                app_testing_objects.RyuICMPPongFilter(
                    self.permit_icmp_request),
                actions=[
                    app_testing_objects.DisableRuleAction(),
                    app_testing_objects.StopSimulationAction(),
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
        key2 = (self.subnet.subnet_id, self.no_permit_port_id)
        rules2 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, raise unexpected packet exception
                app_testing_objects.RyuICMPPongFilter(
                    self.no_permit_icmp_request),
                actions=[
                    raise_action
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
        key3 = (self.subnet.subnet_id, self.port3.port_id)
        rules3 = [
            app_testing_objects.PortPolicyRule(
                # Detect ping from port1, reply with pong
                app_testing_objects.RyuICMPPingFilter(
                    self.permit_icmp_request),
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
                    self.no_permit_icmp_request),
                actions=[
                    raise_action
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

    def _create_ping_packet(self, src_port, dst_port):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=src_port.port.get_logical_port().get_mac(),
            dst=dst_port.port.get_logical_port().get_mac(),
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=src_port.port.get_logical_port().get_ip(),
            dst=dst_port.port.get_logical_port().get_ip(),
            proto=ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
        )
        icmp_id = int(time.mktime(time.gmtime())) & 0xffff
        icmp_seq = 0
        icmp = ryu.lib.packet.icmp.icmp(
            type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=ryu.lib.packet.icmp.echo(id_=icmp_id,
                                          seq=icmp_seq,
                                          data=self._create_random_string())
        )
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result, icmp

    def _create_random_string(self, length=16):
        alphabet = string.printable
        return ''.join([random.choice(alphabet) for _ in range(length)])

    def _create_pong_packet(self, buf):
        pkt = ryu.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
        ip = pkt.get_protocol(ryu.lib.packet.ipv4.ipv4)
        icmp = pkt.get_protocol(ryu.lib.packet.icmp.icmp)

        src_mac = ether.dst
        dst_mac = ether.src
        ether.src = src_mac
        ether.dst = dst_mac
        self.assertEqual(
            dst_mac,
            self.port1.port.get_logical_port().get_mac()
        )
        self.assertEqual(
            src_mac,
            self.port3.port.get_logical_port().get_mac()
        )

        src_ip = ip.dst
        dst_ip = ip.src
        ip.src = src_ip
        ip.dst = dst_ip
        self.assertEqual(
            src_ip,
            self.port3.port.get_logical_port().get_ip()
        )
        self.assertEqual(
            dst_ip,
            self.port1.port.get_logical_port().get_ip()
        )

        icmp.type = ryu.lib.packet.icmp.ICMP_ECHO_REPLY
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
            self.permit_port_id, self.no_permit_port_id = \
                self.no_permit_port_id, self.permit_port_id
            self.permit_icmp_request, self.no_permit_icmp_request = \
                self.no_permit_icmp_request, self.permit_icmp_request

            self.port3.update(
                {"security_groups": [self.active_security_group_id]})

            time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)

            self._update_policy()

        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def test_icmp_ping_pong(self):
        # the rules of the initial security group associated with port3
        # only let icmp echo requests from port1 pass.
        self.policy.start(self.topology)
        self.policy.wait(30)

        # switch the associated security group with port3 to a new security
        # group, and rules of this security group only let icmp echo requests
        # from port2 pass.
        self._switch_to_another_security_group()
        time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)

        self.policy.start(self.topology)
        self.policy.wait(30)

        # switch the associated security group with port3 to the initial
        # security group
        self._switch_to_another_security_group()
        time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)

        self.policy.start(self.topology)
        self.policy.wait(30)

        ovs = test_utils.OvsFlowsParser()
        LOG.info(_LI("flows are: %s"),
                 ovs.get_ovs_flows(self.integration_bridge))

        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]


class TestPortSecApp(test_base.DFTestBase):
    def setUp(self):
        super(TestPortSecApp, self).setUp()
        self.topology = None
        self.policy = None
        self._ping = None
        self.icmp_id_cursor = int(time.mktime(time.gmtime())) & 0xffff
        try:
            security_group = self.store(objects.SecGroupTestObj(
                self.neutron,
                self.nb_api))
            security_group_id = security_group.create()
            self.assertTrue(security_group.exists())

            egress_rule_info = {'ethertype': 'IPv4',
                                'direction': 'egress',
                                'protocol': 'icmp'}
            egress_rule_id = security_group.rule_create(
                secrule=egress_rule_info)
            self.assertTrue(security_group.rule_exists(egress_rule_id))

            ingress_rule_info = {'ethertype': 'IPv4',
                                 'direction': 'ingress',
                                 'protocol': 'icmp',
                                 'remote_ip_prefix': "192.168.196.0/24"}
            ingress_rule_id = security_group.rule_create(
                secrule=ingress_rule_info)
            self.assertTrue(security_group.rule_exists(ingress_rule_id))

            self.topology = self.store(
                app_testing_objects.Topology(
                    self.neutron,
                    self.nb_api
                )
            )
            self.subnet = self.topology.create_subnet(
                cidr='192.168.196.0/24'
            )
            self.port1 = self.subnet.create_port()
            self.port1.update({
                "allowed_address_pairs": [
                    {"ip_address": "192.168.196.100",
                     "mac_address": "10:20:99:99:99:99"}
                ]
            })
            self.port2 = self.subnet.create_port([security_group_id])

            time.sleep(test_utils.DEFAULT_CMD_TIMEOUT)

            port_policies = self._create_port_policies()
            self.policy = self.store(
                app_testing_objects.Policy(
                    initial_actions=[
                        app_testing_objects.SendAction(
                            self.subnet.subnet_id,
                            self.port1.port_id,
                            self._create_ping_using_fake_ip
                        ),
                        app_testing_objects.SendAction(
                            self.subnet.subnet_id,
                            self.port1.port_id,
                            self._create_ping_using_fake_mac
                        ),
                        app_testing_objects.SendAction(
                            self.subnet.subnet_id,
                            self.port1.port_id,
                            self._create_ping_using_vm_ip_mac
                        ),
                        app_testing_objects.SendAction(
                            self.subnet.subnet_id,
                            self.port1.port_id,
                            self._create_ping_using_allowed_address_pair
                        ),
                    ],
                    port_policies=port_policies,
                    unknown_port_action=app_testing_objects.IgnoreAction()
                )
            )
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _create_ping_request(self, src_ip, src_mac, dst_port):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=src_mac,
            dst=dst_port.port.get_logical_port().get_mac(),
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=src_ip,
            dst=dst_port.port.get_logical_port().get_ip(),
            proto=ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
        )
        icmp_id = self.icmp_id_cursor & 0xffff
        self.icmp_id_cursor += 1
        icmp_seq = 0
        icmp = ryu.lib.packet.icmp.icmp(
            type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=ryu.lib.packet.icmp.echo(id_=icmp_id,
                                          seq=icmp_seq,
                                          data=self._create_random_string())
        )
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result, icmp

    def _create_port_policies(self):
        ignore_action = app_testing_objects.IgnoreAction()
        key = (self.subnet.subnet_id, self.port2.port_id)
        # when port2 receive both two packets (one using vm fixed ip and mac,
        # another using one of the allowed address pairs),
        # stop this simulation.
        count_action = app_testing_objects.CountAction(
            2, app_testing_objects.StopSimulationAction()
        )
        rules = [
            app_testing_objects.PortPolicyRule(
                app_testing_objects.RyuICMPPingFilter(
                    self._get_ping_using_vm_ip_mac),
                actions=[
                    count_action,
                    app_testing_objects.DisableRuleAction(),
                ]
            ),
            app_testing_objects.PortPolicyRule(
                app_testing_objects.RyuICMPPingFilter(
                    self._get_ping_using_allowed_address_pair_ip_mac),
                actions=[
                    count_action,
                    app_testing_objects.DisableRuleAction(),
                ]
            ),
            app_testing_objects.PortPolicyRule(
                app_testing_objects.RyuICMPPingFilter(
                    self._get_ping_using_fake_ip),
                actions=[
                    app_testing_objects.RaiseAction("a packet with a fake "
                                                    "ip passed")
                ]
            ),
            app_testing_objects.PortPolicyRule(
                app_testing_objects.RyuICMPPingFilter(
                    self._get_ping_using_fake_mac),
                actions=[
                    app_testing_objects.RaiseAction("a packet with a fake "
                                                    "mac passed")
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
        policy = app_testing_objects.PortPolicy(
            rules=rules,
            default_action=raise_action
        )

        return {
            key: policy
        }

    def _create_ping_using_vm_ip_mac(self, buf):
        ip = self.port1.port.get_logical_port().get_ip()
        mac = self.port1.port.get_logical_port().get_mac()

        result, icmp = self._create_ping_request(ip, mac, self.port2)
        self._ping_using_vm_ip_mac = icmp
        return result.data

    def _create_ping_using_allowed_address_pair(self, buf):
        pairs = self.port1.port.get_logical_port().get_allow_address_pairs()
        ip = pairs[0]["ip_address"]
        mac = pairs[0]["mac_address"]

        result, icmp = self._create_ping_request(ip, mac, self.port2)
        self._ping_using_allowed_address_pair = icmp
        return result.data

    def _create_ping_using_fake_ip(self, buf):
        fake_ip = "1.2.3.4"
        mac = self.port1.port.get_logical_port().get_mac()

        result, icmp = self._create_ping_request(fake_ip, mac, self.port2)
        self._ping_using_fake_ip = icmp
        return result.data

    def _create_ping_using_fake_mac(self, buf):
        ip = self.port1.port.get_logical_port().get_ip()
        fake_mac = "00:11:22:33:44:55"

        result, icmp = self._create_ping_request(ip, fake_mac, self.port2)
        self._ping_using_fake_mac = icmp
        return result.data

    def _get_ping_using_vm_ip_mac(self):
        return self._ping_using_vm_ip_mac

    def _get_ping_using_allowed_address_pair_ip_mac(self):
        return self._ping_using_allowed_address_pair

    def _get_ping_using_fake_ip(self):
        return self._ping_using_fake_ip

    def _get_ping_using_fake_mac(self):
        return self._ping_using_fake_mac

    def _create_random_string(self, length=16):
        alphabet = string.printable
        return ''.join([random.choice(alphabet) for _ in range(length)])

    def test_icmp_ping_using_different_ip_mac(self):
        self.policy.start(self.topology)
        self.policy.wait(30)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]
