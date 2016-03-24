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
import ryu.lib.packet
import string
import sys
import time

from dragonflow._i18n import _LI
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import utils as test_utils
from dragonflow.tests.fullstack import test_base

from oslo_log import log

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
                ['ovs-ofctl', 'show', 'br-int'],
                True
            )
            test_utils.print_command(
                ['ovs-ofctl', 'dump-flows', 'br-int'],
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
                str(arp_packet),
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
        pkt = ryu.lib.packet.packet.Packet(offer_buf)
        offer = pkt.get_protocol(ryu.lib.packet.dhcp.dhcp)
        self.assertEqual(
            self.port1.port.get_logical_port().get_ip(),
            offer.yiaddr
        )
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

    def _create_port_policies(self):
        ignore_action = app_testing_objects.IgnoreAction()
        key1 = (self.subnet1.subnet_id, self.port1.port_id)
        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect dhcp offer
                app_testing_objects.RyuDHCPOfferFilter(),
                actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        self._create_dhcp_request
                    ),
                    app_testing_objects.DisableRuleAction(),
                ]
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
