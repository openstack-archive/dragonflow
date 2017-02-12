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

import sys
import time

from neutron.agent.common import utils
from oslo_log import log
import ryu.lib.packet
from ryu.ofproto import inet


from dragonflow._i18n import _LI
from dragonflow import conf as cfg
from dragonflow.controller.common import constants
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
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
            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
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
            dst=constants.BROADCAST_MAC,
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_ARP,
        )
        arp = ryu.lib.packet.arp.arp_ip(
            opcode=ryu.lib.packet.arp.ARP_REQUEST,
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
        self.policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]


class TestNeighborAdvertiser(test_base.DFTestBase):

    def setUp(self):
        super(TestNeighborAdvertiser, self).setUp()
        self.topology = None
        self.policy = None
        try:
            # Disable Duplicate Address Detection requests from the interface
            self.dad_conf = utils.execute(['sysctl', '-n',
                'net.ipv6.conf.default.accept_dad'])
            utils.execute(['sysctl', '-w',
                'net.ipv6.conf.default.accept_dad=0'], run_as_root=True)
            # Disable Router Solicitation requests from the interface
            self.router_solicit_conf = utils.execute(['sysctl', '-n',
                'net.ipv6.conf.default.router_solicitations'])
            utils.execute(['sysctl', '-w',
                'net.ipv6.conf.default.router_solicitations=0'],
                run_as_root=True)
            self.topology = app_testing_objects.Topology(
                self.neutron,
                self.nb_api)
            subnet1 = self.topology.create_subnet(cidr='1111:1111:1111::/64')
            port1 = subnet1.create_port()
            port2 = subnet1.create_port()
            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
            # Create Neighbor Solicitation packet
            ns_packet = self._create_ns_request(
                src_port=port1.port.get_logical_port(),
                dst_port=port2.port.get_logical_port(),
            )
            send_ns_request = app_testing_objects.SendAction(
                subnet1.subnet_id,
                port1.port_id,
                str(ns_packet)
            )
            ignore_action = app_testing_objects.IgnoreAction()
            log_action = app_testing_objects.LogAction()
            key1 = (subnet1.subnet_id, port1.port_id)
            adv_filter = app_testing_objects.RyuNeighborAdvertisementFilter()
            port_policies = {
                key1: app_testing_objects.PortPolicy(
                    rules=[
                        app_testing_objects.PortPolicyRule(
                            # Detect advertisements
                            adv_filter,
                            actions=[
                                log_action,
                                app_testing_objects.StopSimulationAction()
                            ]
                        ),
                        app_testing_objects.PortPolicyRule(
                            # Filter local VM's Multicast requests
                            app_testing_objects.RyuIpv6MulticastFilter(),
                            actions=[ignore_action]
                        )
                    ],
                    default_action=app_testing_objects.RaiseAction(
                        "Unexpected packet"
                    )
                ),
            }
            self.policy = app_testing_objects.Policy(
                initial_actions=[send_ns_request],
                port_policies=port_policies,
                unknown_port_action=ignore_action
            )
        except Exception:
            if self.topology:
                self.topology.close()
            raise
        self.store(self.topology)
        self.store(self.policy)

    def _create_ns_request(self, src_port, dst_port):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=src_port.get_mac(),
            dst=constants.BROADCAST_MAC,
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IPV6,
        )
        ipv6 = ryu.lib.packet.ipv6.ipv6(
            src=src_port.get_ip(),
            dst=dst_port.get_ip(),
            nxt=inet.IPPROTO_ICMPV6
        )
        icmpv6 = ryu.lib.packet.icmpv6.icmpv6(
            type_=ryu.lib.packet.icmpv6.ND_NEIGHBOR_SOLICIT,
            data=ryu.lib.packet.icmpv6.nd_neighbor(
                dst=dst_port.get_ip()
            )
        )
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ipv6)
        result.add_protocol(icmpv6)
        result.serialize()
        return result.data

    def tearDown(self):
        super(TestNeighborAdvertiser, self).tearDown()
        self.topology.close()
        self.policy.close()
        utils.execute(['sysctl', '-w', 'net.ipv6.conf.default.accept_dad={}'.
            format(self.dad_conf)], run_as_root=True)
        utils.execute(['sysctl', '-w',
            'net.ipv6.conf.default.router_solicitations={}'.
            format(self.router_solicit_conf)], run_as_root=True)

    def test_simple_response(self):
        """
        2 ports on 1 subnet. 1 port asks for MAC of other.
        Policy:
            port1:
                Send Neighbor Solicitation request
                Receive Neighbor Advertisement
            port2:
                Do nothing
        """
        self.policy.start(self.topology)
        self.policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]


class TestDHCPApp(test_base.DFTestBase):

    def _create_topology(self, enable_dhcp=True, cidr='192.168.11.0/24'):
        try:
            self.topology = self.store(
                app_testing_objects.Topology(
                    self.neutron,
                    self.nb_api
                )
            )
            self.subnet1 = self.topology.create_subnet(
                cidr=cidr, enable_dhcp=enable_dhcp)
            self.port1 = self.subnet1.create_port()
            self.port2 = self.subnet1.create_port()
            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _create_udp_packet_for_dhcp(self,
            dst_mac=constants.BROADCAST_MAC,
            src_ip='0.0.0.0',
            dst_ip=constants.BROADCAST_IP):
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
            src_port=constants.DHCP_CLIENT_PORT,
            dst_port=constants.DHCP_SERVER_PORT,
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
        self._create_topology()
        self._test_enable_dhcp()

    def _check_dhcp_block_rule(self, flows, ofport=None):
        for flow in flows:
            if (int(flow['table']) == constants.DHCP_TABLE and
                'drop' in flow['actions']):
                if ofport is None or 'inport=' + ofport in flow['match']:
                    return True
        return False

    def test_dhcp_app_dos_block(self):
        def internal_predicate():
            ovs = test_utils.OvsFlowsParser()
            return (self._check_dhcp_block_rule(
                ovs.dump(self.integration_bridge)))

        self._create_topology()
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
        test_utils.wait_until_true(internal_predicate,
                                   const.DEFAULT_RESOURCE_READY_TIMEOUT,
                                   1, None)

    def _test_disable_dhcp(self):
        dhcp_packet = self._create_dhcp_discover()
        send_dhcp_offer = app_testing_objects.SendAction(
            self.subnet1.subnet_id,
            self.port1.port_id,
            str(dhcp_packet)
        )
        key = (self.subnet1.subnet_id, self.port1.port_id)
        rules = [
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
                    app_testing_objects.IgnoreAction()
                ]
            ),
        ]
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        port_policy = app_testing_objects.PortPolicy(
            rules=rules,
            default_action=raise_action
        )
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[send_dhcp_offer],
                port_policies={key: port_policy},
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )
        policy.start(self.topology)
        # Since there is no dhcp response, we are expecting timeout
        # exception here.
        self.assertRaises(
            app_testing_objects.TimeoutException,
            policy.wait,
            const.DEFAULT_RESOURCE_READY_TIMEOUT)
        policy.stop()
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def _test_enable_dhcp(self):
        # Create policy
        dhcp_packet = self._create_dhcp_discover()
        send_dhcp_offer = app_testing_objects.SendAction(
            self.subnet1.subnet_id,
            self.port1.port_id,
            str(dhcp_packet)
        )
        port_policies = self._create_port_policies()
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[send_dhcp_offer],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def test_disable_enable_dhcp(self):
        self._create_topology(enable_dhcp=False)
        self._test_disable_dhcp()
        self.subnet1.update({'enable_dhcp': True})
        self._test_enable_dhcp()


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
            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _create_port_policies(self, connected=True):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        key1 = (self.subnet1.subnet_id, self.port1.port_id)
        if connected:
            actions = [app_testing_objects.DisableRuleAction(),
                       app_testing_objects.StopSimulationAction()]
        else:
            actions = [raise_action]

        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect pong, end simulation
                app_testing_objects.RyuICMPPongFilter(self._get_ping),
                actions=actions
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
        if connected:
            actions = [app_testing_objects.SendAction(self.subnet2.subnet_id,
                                                      self.port2.port_id,
                                                      self._create_pong_packet
                                                      ),
                       app_testing_objects.DisableRuleAction()]
        else:
            actions = [raise_action]

        rules2 = [
            app_testing_objects.PortPolicyRule(
                # Detect ping, reply with pong
                app_testing_objects.RyuICMPPingFilter(),
                actions=actions
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
        return {
            key1: policy1,
            key2: policy2,
        }

    def _create_ping_packet(self, dst_ip, ttl=255):
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
            dst=dst_ip,
            ttl=ttl,
            proto=ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
        )
        icmp = ryu.lib.packet.icmp.icmp(
            type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=ryu.lib.packet.icmp.echo(data=self._create_random_string())
        )
        self._ping = icmp
        self._ip = ip
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result.data

    def _get_ping(self):
        return self._ping

    def _get_ip(self):
        return self._ip

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

    def _test_icmp_address(self, dst_ip):
        port_policies = self._create_port_policies()
        initial_packet = self._create_ping_packet(dst_ip)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        str(initial_packet)
                    ),
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def test_icmp_ping_pong(self):
        self._test_icmp_address(self.port2.port.get_logical_port().get_ip())

    def test_icmp_router_interfaces(self):
        self._test_icmp_address('192.168.12.1')

    def test_icmp_other_router_interface(self):
        self._test_icmp_address('192.168.13.1')

    def test_reconnect_of_controller(self):
        cmd = ["ovs-vsctl", "get-controller", cfg.CONF.df.integration_bridge]
        controller = utils.execute(cmd, run_as_root=True).strip()

        cmd[1] = "del-controller"
        utils.execute(cmd, run_as_root=True)

        dst_ip = self.port2.port.get_logical_port().get_ip()
        port_policies = self._create_port_policies(connected=False)
        initial_packet = self._create_ping_packet(dst_ip)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        str(initial_packet)
                    ),
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )
        policy.start(self.topology)
        # Since there is no OpenFlow in vswitch, we are expecting timeout
        # exception here.
        self.assertRaises(
            app_testing_objects.TimeoutException,
            policy.wait,
            const.DEFAULT_RESOURCE_READY_TIMEOUT)
        policy.stop()
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

        cmd[1] = "set-controller"
        cmd.append(controller)
        utils.execute(cmd, run_as_root=True)
        time.sleep(const.DEFAULT_CMD_TIMEOUT)
        self._test_icmp_address(dst_ip)

    def test_icmp_ttl_packet(self):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        rules = [
            app_testing_objects.PortPolicyRule(
                # Detect ICMP time exceed, end simulation
                app_testing_objects.RyuICMPTimeExceedFilter(self._get_ip),
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
        policy = app_testing_objects.PortPolicy(
            rules=rules,
            default_action=raise_action
        )
        key = (self.subnet1.subnet_id, self.port1.port_id)
        initial_packet = self._create_ping_packet(
            self.port2.port.get_logical_port().get_ip(), ttl=1)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        str(initial_packet)
                    ),
                ],
                port_policies={key: policy},
                unknown_port_action=ignore_action
            )
        )
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]


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

            security_group3 = self.store(objects.SecGroupTestObj(
                self.neutron,
                self.nb_api))
            security_group_id3 = security_group3.create()
            self.assertTrue(security_group3.exists())

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
            self.port4 = self.subnet.create_port()

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

            self.port4.update(
                {'allowed_address_pairs': [{'ip_address': '192.168.14.200'}]})

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

            ingress_rule_info3 = {
                'ethertype': 'IPv4',
                'direction': 'ingress',
                'protocol': 'icmp',
                'remote_group_id':
                    self.topology.fake_default_security_group.secgroup_id}
            ingress_rule_id3 = security_group3.rule_create(
                secrule=ingress_rule_info3)
            self.assertTrue(security_group3.rule_exists(ingress_rule_id3))

            self.active_security_group_id = security_group_id
            self.inactive_security_group_id = security_group_id2
            self.permit_port_id = self.port1.port_id
            self.no_permit_port_id = self.port2.port_id
            self.permit_icmp_request = self._get_icmp_request1
            self.no_permit_icmp_request = self._get_icmp_request2
            self.allowed_address_pairs_security_group_id = security_group_id3

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

            self._update_policy()
            self._create_allowed_address_pairs_policy()
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
                        str(packet1.data)
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

    def _create_allowed_address_pairs_port_policies(self):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        key = (self.subnet.subnet_id, self.port3.port_id)
        rules = [
            app_testing_objects.PortPolicyRule(
                # Detect ping from port4, end the test
                app_testing_objects.RyuICMPPingFilter(
                    self._get_allowed_address_pairs_icmp_request),
                actions=[
                    app_testing_objects.DisableRuleAction(),
                    app_testing_objects.StopSimulationAction()
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
            rules=rules,
            default_action=raise_action
        )
        return {
            key: policy1,
        }

    def _create_ping_packet(self, src_port, dst_port):
        allowed_address_pairs = \
            src_port.port.get_logical_port().get_allowed_address_pairs()
        if allowed_address_pairs:
            src_mac = allowed_address_pairs[0]['mac_address']
            src_ip = allowed_address_pairs[0]['ip_address']
        else:
            src_mac = src_port.port.get_logical_port().get_mac()
            src_ip = src_port.port.get_logical_port().get_ip()

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

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

            self._update_policy()

        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def test_icmp_ping_pong(self):
        # the rules of the initial security group associated with port3
        # only let icmp echo requests from port1 pass.
        self.policy.start(self.topology)
        self.policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # switch the associated security group with port3 to a new security
        # group, and rules of this security group only let icmp echo requests
        # from port2 pass.
        self._switch_to_another_security_group()
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        self.policy.start(self.topology)
        self.policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # switch the associated security group with port3 to the initial
        # security group
        self._switch_to_another_security_group()
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        self.policy.start(self.topology)
        self.policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        ovs = test_utils.OvsFlowsParser()
        LOG.info(_LI("flows are: %s"),
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

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

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
        pairs = self.port1.port.get_logical_port().get_allowed_address_pairs()
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

    def test_icmp_ping_using_different_ip_mac(self):
        self.policy.start(self.topology)
        self.policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]


class TestAllowedAddressPairsDetectActive(test_base.DFTestBase):

    def _create_policy_to_reply_arp_request(self):
        ignore_action = app_testing_objects.IgnoreAction()
        key1 = (self.subnet.subnet_id, self.port.port_id)
        port_policies = {
            key1: app_testing_objects.PortPolicy(
                rules=[
                    app_testing_objects.PortPolicyRule(
                        # Detect arp requests
                        app_testing_objects.RyuARPRequestFilter(
                            self.allowed_address_pair_ip_address
                        ),
                        actions=[
                            app_testing_objects.SendAction(
                                self.subnet.subnet_id,
                                self.port.port_id,
                                self._create_arp_response
                            ),
                            app_testing_objects.WaitAction(5),
                            app_testing_objects.DisableRuleAction(),
                            app_testing_objects.StopSimulationAction()
                        ]
                    )
                ],
                default_action=ignore_action
            ),
        }

        return port_policies

    def setUp(self):
        super(TestAllowedAddressPairsDetectActive, self).setUp()
        self.topology = None
        self.policy = None
        self.allowed_address_pair_ip_address = None
        self.allowed_address_pair_mac_address = None
        try:
            self.topology = self.store(app_testing_objects.Topology(
                self.neutron,
                self.nb_api))
            subnet = self.topology.create_subnet(cidr='192.168.98.0/24')
            self.subnet = subnet
            port = subnet.create_port()
            self.port = port

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

            port.update({'allowed_address_pairs': [{
                'ip_address': '192.168.98.100'}]})

            time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

            port_lport = port.port.get_logical_port()
            self.assertIsNotNone(port_lport)

            allowed_address_pairs = port_lport.get_allowed_address_pairs()
            self.assertIsNotNone(allowed_address_pairs)

            self.allowed_address_pair_ip_address = \
                allowed_address_pairs[0]['ip_address']
            self.allowed_address_pair_mac_address = \
                allowed_address_pairs[0]['mac_address']

            # Create policy to reply arp request sent from controller
            self.policy = self.store(
                app_testing_objects.Policy(
                    initial_actions=[],
                    port_policies=self._create_policy_to_reply_arp_request(),
                    unknown_port_action=app_testing_objects.IgnoreAction()
                )
            )
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _create_arp_response(self, buf):
        pkt = ryu.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
        arp = pkt.get_protocol(ryu.lib.packet.arp.arp)

        src_mac = self.allowed_address_pair_mac_address
        dst_mac = ether.src
        ether.src = src_mac
        ether.dst = dst_mac

        self.assertEqual(
            arp.dst_ip,
            self.allowed_address_pair_ip_address
        )
        arp_sha = self.allowed_address_pair_mac_address
        arp_spa = self.allowed_address_pair_ip_address
        arp_tha = arp.src_mac
        arp_tpa = arp.src_ip
        arp.opcode = ryu.lib.packet.arp.ARP_REPLY
        arp.src_mac = arp_sha
        arp.src_ip = arp_spa
        arp.dst_mac = arp_tha
        arp.dst_ip = arp_tpa

        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ether)
        result.add_protocol(arp)
        result.serialize()
        return result.data

    def _is_expected_active_port(self, active_port):
        lport = self.port.port.get_logical_port()
        expected_id = (lport.get_lswitch_id() +
                       self.allowed_address_pair_ip_address)
        if expected_id != expected_id:
            return False
        if lport.get_topic() != active_port.get_topic():
            return False
        if lport.get_id() != active_port.get_detected_lport_id():
            return False
        if lport.get_lswitch_id() != active_port.get_network_id():
            return False
        if self.allowed_address_pair_ip_address != active_port.get_ip():
            return False
        if self.allowed_address_pair_mac_address != \
                active_port.get_detected_mac():
            return False
        return True

    def _if_the_expected_active_port_exists(self):
        active_ports = self.nb_api.get_active_ports()
        for active_port in active_ports:
            if self._is_expected_active_port(active_port):
                return True
        return False

    def test_detected_active_port(self):
        self.policy.start(self.topology)
        self.policy.wait(30)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]

        # check if the active port exists in DF DB
        self.assertTrue(self._if_the_expected_active_port_exists())

        # clear allowed address pairs configuration from the lport
        self.port.update({'allowed_address_pairs': []})
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # check if the active port was removed from DF DB
        self.assertFalse(self._if_the_expected_active_port_exists())


class TestDNATApp(test_base.DFTestBase):
    def setUp(self):
        super(TestDNATApp, self).setUp()

        self.topology = None
        try:
            self.topology = self.store(
                app_testing_objects.Topology(
                    self.neutron,
                    self.nb_api
                )
            )
            self.subnet = self.topology.create_subnet()
            self.port = self.subnet.create_port()
            self.router = self.topology.create_router([
                self.subnet.subnet_id
            ])
            ext_net_id = self.topology.create_external_network([
                self.router.router_id
            ])
            self.fip = self.store(
                objects.FloatingipTestObj(self.neutron, self.nb_api))
            self.fip.create({'floating_network_id': ext_net_id,
                             'port_id': self.port.port.port_id})
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _create_icmp_test_port_policies(self, icmp_filter):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        key = (self.subnet.subnet_id, self.port.port_id)
        rules = [
            app_testing_objects.PortPolicyRule(
                # Detect ICMP, end simulation
                icmp_filter(self._get_ip),
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
        policy = app_testing_objects.PortPolicy(
            rules=rules,
            default_action=raise_action
        )
        return {key: policy}

    def _create_packet(self, dst_ip, proto, ttl=255):
        router_interface = self.router.router_interfaces[
            self.subnet.subnet_id
        ]
        router_interface_port = self.neutron.show_port(
            router_interface['port_id']
        )
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=self.port.port.get_logical_port().get_mac(),
            dst=router_interface_port['port']['mac_address'],
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=self.port.port.get_logical_port().get_ip(),
            dst=dst_ip,
            ttl=ttl,
            proto=proto,
        )
        if proto == ryu.lib.packet.ipv4.inet.IPPROTO_ICMP:
            ip_data = ryu.lib.packet.icmp.icmp(
                type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
                data=ryu.lib.packet.icmp.echo(
                    data=self._create_random_string())
            )
        elif proto == ryu.lib.packet.ipv4.inet.IPPROTO_UDP:
            ip_data = ryu.lib.packet.udp.udp(
                dst_port=33534,
            )
        self._ip = ip
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(ip_data)
        result.serialize()
        return result.data

    def _get_ip(self):
        return self._ip

    def test_icmp_ttl_packet(self):
        ignore_action = app_testing_objects.IgnoreAction()
        initial_packet = self._create_packet(
            self.topology.external_network.get_gw_ip(),
            ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
            ttl=1)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.port.port_id,
                        str(initial_packet)
                    ),
                ],
                port_policies=self._create_icmp_test_port_policies(
                    app_testing_objects.RyuICMPTimeExceedFilter),
                unknown_port_action=ignore_action
            )
        )
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def _create_rate_limit_port_policies(self, rate, icmp_filter):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        # Disable port policy rule, so that any further packets will hit the
        # default action, which is raise_action in this case.
        count_action = app_testing_objects.CountAction(
            rate, app_testing_objects.DisableRuleAction())

        key = (self.subnet.subnet_id, self.port.port_id)
        rules = [
            app_testing_objects.PortPolicyRule(
                # Detect ICMP, end simulation
                icmp_filter(self._get_ip),
                actions=[count_action]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.RyuARPGratuitousFilter(),
                actions=[ignore_action]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 packets
                app_testing_objects.RyuIPv6Filter(),
                actions=[ignore_action]
            ),
        ]
        policy = app_testing_objects.PortPolicy(
            rules=rules,
            default_action=raise_action
        )
        return {key: policy}

    def test_ttl_packet_rate_limit(self):
        initial_packet = self._create_packet(
            self.topology.external_network.get_gw_ip(),
            ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
            ttl=1)
        send_action = app_testing_objects.SendAction(
            self.subnet.subnet_id,
            self.port.port_id,
            str(initial_packet))
        ignore_action = app_testing_objects.IgnoreAction()
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    send_action,
                    send_action,
                    send_action,
                    send_action,
                ],
                port_policies=self._create_rate_limit_port_policies(
                    cfg.CONF.df_dnat_app.dnat_ttl_invalid_max_rate,
                    app_testing_objects.RyuICMPTimeExceedFilter),
                unknown_port_action=ignore_action
            )
        )
        policy.start(self.topology)
        # Since the rate limit, we expect timeout to wait for 4th packet hit
        # the policy.
        self.assertRaises(
            app_testing_objects.TimeoutException,
            policy.wait,
            const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def test_nat_embedded_packet(self):
        ignore_action = app_testing_objects.IgnoreAction()
        self.port.port.update({"security_groups": []})

        initial_packet = self._create_packet(
            self.topology.external_network.get_gw_ip(),
            ryu.lib.packet.ipv4.inet.IPPROTO_UDP)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet.subnet_id,
                        self.port.port_id,
                        str(initial_packet)
                    ),
                ],
                port_policies=self._create_icmp_test_port_policies(
                    app_testing_objects.RyuICMPUnreachFilter),
                unknown_port_action=ignore_action
            )
        )
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def test_nat_embedded_rate_limit(self):
        self.port.port.update({"security_groups": []})
        initial_packet = self._create_packet(
            self.topology.external_network.get_gw_ip(),
            ryu.lib.packet.ipv4.inet.IPPROTO_UDP)
        send_action = app_testing_objects.SendAction(
            self.subnet.subnet_id,
            self.port.port_id,
            str(initial_packet))
        ignore_action = app_testing_objects.IgnoreAction()
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    send_action,
                    send_action,
                    send_action,
                    send_action,
                ],
                port_policies=self._create_rate_limit_port_policies(
                    cfg.CONF.df_dnat_app.dnat_icmp_error_max_rate,
                    app_testing_objects.RyuICMPUnreachFilter),
                unknown_port_action=ignore_action
            )
        )
        policy.start(self.topology)
        # Since the rate limit, we expect timeout to wait for 4th packet hit
        # the policy.
        self.assertRaises(
            app_testing_objects.TimeoutException,
            policy.wait,
            const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]
