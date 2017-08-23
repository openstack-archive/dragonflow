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

import copy
import netaddr
import struct
import sys
import time

from neutron.agent.common import ip_lib
from neutron.agent.common import utils
from neutron_lib import constants as n_const
from oslo_log import log
import ryu.lib.packet
from ryu.lib.packet import dhcp
from ryu.ofproto import inet
import testtools

from dragonflow import conf as cfg
from dragonflow.controller.common import constants
from dragonflow.db.models import active_port
from dragonflow.db.models import l2
from dragonflow.db.models import l3
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
            LOG.info('Port1 name: {}'.format(port1.tap.tap.name))
            LOG.info('Port2 name: {}'.format(port2.tap.tap.name))
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
                arp_packet,
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
            src=str(src_port.mac),
            dst=str(constants.BROADCAST_MAC),
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_ARP,
        )
        arp = ryu.lib.packet.arp.arp_ip(
            opcode=ryu.lib.packet.arp.ARP_REQUEST,
            src_mac=str(src_port.mac), src_ip=str(src_port.ip),
            dst_mac='00:00:00:00:00:00', dst_ip=str(dst_port.ip),
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
                           'net.ipv6.conf.default.accept_dad=0'],
                          run_as_root=True)
            # Disable Router Solicitation requests from the interface
            self.router_solicit_conf = utils.execute(
                ['sysctl', '-n', 'net.ipv6.conf.default.router_solicitations'])
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
                ns_packet,
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
            src=str(src_port.mac),
            dst=str(constants.BROADCAST_MAC),
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IPV6,
        )
        ipv6 = ryu.lib.packet.ipv6.ipv6(
            src=str(src_port.ip),
            dst=str(dst_port.ip),
            nxt=inet.IPPROTO_ICMPV6
        )
        icmpv6 = ryu.lib.packet.icmpv6.icmpv6(
            type_=ryu.lib.packet.icmpv6.ND_NEIGHBOR_SOLICIT,
            data=ryu.lib.packet.icmpv6.nd_neighbor(
                dst=str(dst_port.ip)
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
            src=str(self.port1.port.get_logical_port().mac),
            dst=str(dst_mac),
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=str(src_ip),
            dst=str(dst_ip),
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
            chaddr=str(self.port1.port.get_logical_port().mac),
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
            str(self.port1.port.get_logical_port().ip),
            offer.yiaddr
        )
        self.assertTrue(is_121_exist(offer))
        if is_renewal:
            ether = pkt.get_protocol(ryu.lib.packet.ethernet.ethernet)
            ip = pkt.get_protocol(ryu.lib.packet.ipv4.ipv4)
            dst_mac = ether.src
            dst_ip = ip.src
            src_ip = self.port1.port.get_logical_port().ip
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
            chaddr=str(self.port1.port.get_logical_port().mac),
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
            app_testing_objects.SendAction(self.subnet1.subnet_id,
                                           self.port1.port_id,
                                           self._create_dhcp_request)]
        if disable_rule:
            actions.append(app_testing_objects.DisableRuleAction())

        testclass = self

        class DHCPAckFilterVerifiesMTU(app_testing_objects.RyuDHCPAckFilter):

            def __init__(self, expected_mtu):
                super(DHCPAckFilterVerifiesMTU, self).__init__()
                self.expected_mtu = expected_mtu

            def __call__(self, buf):
                result = super(DHCPAckFilterVerifiesMTU, self).__call__(buf)
                if not result:
                    return result
                pkt = ryu.lib.packet.packet.Packet(buf)
                pkt_dhcp_protocol = pkt.get_protocol(dhcp.dhcp)
                for option in pkt_dhcp_protocol.options.option_list:
                    if option.tag == dhcp.DHCP_INTERFACE_MTU_OPT:
                        mtu = struct.unpack('!H', option.value)
                        testclass.assertEqual((self.expected_mtu,), mtu)
                return result

        lport1 = self.port1.port.get_logical_port()
        lswitch_ref = lport1.lswitch
        lswitch = self.nb_api.get(lswitch_ref)
        expected_mtu = lswitch.mtu
        rules1 = [
            app_testing_objects.PortPolicyRule(
                # Detect dhcp offer
                app_testing_objects.RyuDHCPOfferFilter(),
                actions
            ),
            app_testing_objects.PortPolicyRule(
                # Detect dhcp acknowledge
                DHCPAckFilterVerifiesMTU(expected_mtu),
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
                DHCPAckFilterVerifiesMTU(expected_mtu),
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
            dhcp_packet,
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
            dhcp_packet,
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
            dhcp_packet,
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
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
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
                # Ignore ARP requests from active port detection app for
                # ports with allowed_address_pairs
                app_testing_objects.RyuARPRequestFilter(),
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

    def _create_packet(self, dst_ip, proto, ttl=255):
        router_interface = self.router.router_interfaces[
            self.subnet1.subnet_id
        ]
        router_interface_port = self.neutron.show_port(
            router_interface['port_id']
        )
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=self.port1.port.get_logical_port().mac,
            dst=router_interface_port['port']['mac_address'],
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=str(self.port1.port.get_logical_port().ip),
            dst=str(dst_ip),
            ttl=ttl,
            proto=proto,
        )
        if proto == ryu.lib.packet.ipv4.inet.IPPROTO_ICMP:
            ip_data = ryu.lib.packet.icmp.icmp(
                type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
                data=ryu.lib.packet.icmp.echo(
                    data=self._create_random_string())
            )
            self._ping = ip_data
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

        lport2 = self.port2.port.get_logical_port()
        self.assertIn(
            src_mac,
            lport2.macs + [
                p.mac_address for p in lport2.allowed_address_pairs or ()
            ]
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
        self.assertIn(
            netaddr.IPAddress(src_ip),
            lport2.ips + [
                p.ip_address for p in lport2.allowed_address_pairs or ()
            ]
        )
        self.assertEqual(
            netaddr.IPAddress(dst_ip),
            self.port1.port.get_logical_port().ip
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
        initial_packet = self._create_packet(
            dst_ip, ryu.lib.packet.ipv4.inet.IPPROTO_ICMP)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        initial_packet,
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
        self._test_icmp_address(self.port2.port.get_logical_port().ip)

    def test_icmp_ping_pong_allowed_address_pair(self):
        port3 = objects.PortTestObj(self.neutron, self.nb_api)
        port3.create(
            port={
                'admin_state_up': True,
                'fixed_ips': [{
                    'subnet_id': self.subnet2.subnet.subnet_id,
                }],
                'network_id': self.subnet2.network.network_id,
            },
        )

        try:
            lport3 = port3.get_logical_port()
            self.port2.port.update(
                {
                    'allowed_address_pairs': [
                        {'ip_address': lport3.ip, 'mac_address': lport3.mac},
                    ],
                },
            )
            lport2 = self.port2.port.get_logical_port()
            self._test_icmp_address(lport2.allowed_address_pairs[0].ip_address)
        finally:
            port3.close()

    def test_icmp_router_interfaces(self):
        self._test_icmp_address('192.168.12.1')

    def test_icmp_other_router_interface(self):
        self._test_icmp_address('192.168.13.1')

    def test_reconnect_of_controller(self):
        cmd = ["ovs-vsctl", "get-controller", cfg.CONF.df.integration_bridge]
        controller = utils.execute(cmd, run_as_root=True).strip()

        cmd[1] = "del-controller"
        utils.execute(cmd, run_as_root=True)

        dst_ip = self.port2.port.get_logical_port().ip
        port_policies = self._create_port_policies(connected=False)
        initial_packet = self._create_packet(
            dst_ip, ryu.lib.packet.ipv4.inet.IPPROTO_ICMP)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        initial_packet,
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

    def _create_icmp_test_port_policies(self, icmp_filter):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
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
        key = (self.subnet1.subnet_id, self.port1.port_id)
        return {key: policy}

    def _create_rate_limit_port_policies(self, rate, icmp_filter):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        # Disable port policy rule, so that any further packets will hit the
        # default action, which is raise_action in this case.
        count_action = app_testing_objects.CountAction(
            rate, app_testing_objects.DisableRuleAction())

        key = (self.subnet1.subnet_id, self.port1.port_id)
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

    def test_icmp_ttl_packet_with_rate_limit(self):
        ignore_action = app_testing_objects.IgnoreAction()
        port_policy = self._create_rate_limit_port_policies(
            cfg.CONF.df_l3_app.router_ttl_invalid_max_rate,
            app_testing_objects.RyuICMPTimeExceedFilter)
        initial_packet = self._create_packet(
            self.port2.port.get_logical_port().ip,
            ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
            ttl=1)
        send_action = app_testing_objects.SendAction(
            self.subnet1.subnet_id,
            self.port1.port_id,
            initial_packet)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    send_action,
                    send_action,
                    send_action,
                    send_action
                ],
                port_policies=port_policy,
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

    @testtools.skip("bug/1706065")
    def test_udp_concrete_router_interface(self):
        # By default, fullstack will start l3 agent. So there will be concrete
        # router interface.
        self.port1.port.update({"security_groups": []})
        ignore_action = app_testing_objects.IgnoreAction()
        port_policy = self._create_icmp_test_port_policies(
            app_testing_objects.RyuICMPUnreachFilter)
        initial_packet = self._create_packet(
            "192.168.12.1", ryu.lib.packet.ipv4.inet.IPPROTO_UDP)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        initial_packet,
                    ),
                ],
                port_policies=port_policy,
                unknown_port_action=ignore_action
            )
        )
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def test_udp_virtual_router_interface_with_rate_limit(self):
        if 'zmq_pubsub_driver' == cfg.CONF.df.pub_sub_driver:
            # NOTE(nick-ma-z): This test case directly calls nb_api which
            # relies on a publisher running on local process. In ZMQ driver,
            # a socket needs to be binded which causes conflicts with other
            # df-services. But in Redis driver, the publisher is virtual and
            # does not actually run which makes this test case work.
            self.skipTest("ZMQ_PUBSUB does not support this test case")
        # Delete the concrete router interface.
        router_port_id = self.router.router_interfaces[
            self.subnet1.subnet_id]['port_id']
        topic = self.router.router_interfaces[
            self.subnet1.subnet_id]['tenant_id']
        self.nb_api.delete(l2.LogicalPort(id=router_port_id, topic=topic))
        lrouter = self.nb_api.get(l3.LogicalRouter(
                                      id=self.router.router.router_id,
                                      topic=topic))
        lrouter.version += 1
        original_lrouter = copy.deepcopy(lrouter)
        lrouter.remove_router_port(router_port_id)
        self.nb_api.update(lrouter)
        # Update router with virtual router interface.
        original_lrouter.version += 1
        self.nb_api.update(original_lrouter)

        time.sleep(const.DEFAULT_CMD_TIMEOUT)
        self.port1.port.update({"security_groups": []})
        ignore_action = app_testing_objects.IgnoreAction()
        port_policy = self._create_rate_limit_port_policies(
            cfg.CONF.df_l3_app.router_port_unreach_max_rate,
            app_testing_objects.RyuICMPUnreachFilter)
        initial_packet = self._create_packet(
            "192.168.12.1", ryu.lib.packet.ipv4.inet.IPPROTO_UDP)
        send_action = app_testing_objects.SendAction(
            self.subnet1.subnet_id,
            self.port1.port_id,
            initial_packet)

        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    send_action,
                    send_action,
                    send_action,
                    send_action
                ],
                port_policies=port_policy,
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

    def _create_extra_route_policies(self, nexthop_port):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        rules = [
            app_testing_objects.PortPolicyRule(
                # The nexthop lport should get the icmp echo request whose
                # destination is the cidr of extra route.
                app_testing_objects.RyuICMPPingFilter(self._get_ping),
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
        key = (self.subnet1.subnet_id, nexthop_port.port_id)
        return {key: policy}

    def test_router_extra_route(self):
        nexthop_port = self.subnet1.create_port()
        nexthop_ip = nexthop_port.port.get_logical_port().ip
        self.router.router.update({"routes": [{"nexthop": nexthop_ip,
                                               "destination": "30.0.0.0/24"}]})
        time.sleep(const.DEFAULT_CMD_TIMEOUT)
        ignore_action = app_testing_objects.IgnoreAction()
        port_policy = self._create_extra_route_policies(nexthop_port)
        initial_packet = self._create_packet(
            "30.0.0.12",
            ryu.lib.packet.ipv4.inet.IPPROTO_ICMP)
        send_action = app_testing_objects.SendAction(
            self.subnet1.subnet_id,
            self.port1.port_id,
            initial_packet)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    send_action
                ],
                port_policies=port_policy,
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
        key1 = (self.subnet.subnet_id, self.permit_port_id)
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
        key2 = (self.subnet.subnet_id, self.no_permit_port_id)
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
        allowed_address_pairs = \
            src_port.port.get_logical_port().allowed_address_pairs
        if allowed_address_pairs:
            src_mac = allowed_address_pairs[0].mac_address
            src_ip = allowed_address_pairs[0].ip_address
        else:
            src_mac = src_port.port.get_logical_port().mac
            src_ip = src_port.port.get_logical_port().ip

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

        src_mac = ether.dst
        dst_mac = ether.src
        ether.src = src_mac
        ether.dst = dst_mac
        self.assertEqual(
            dst_mac,
            self.port1.port.get_logical_port().mac
        )
        self.assertEqual(
            src_mac,
            self.port3.port.get_logical_port().mac
        )

        src_ip = ip.dst
        dst_ip = ip.src
        ip.src = src_ip
        ip.dst = dst_ip
        self.assertEqual(
            netaddr.IPAddress(src_ip),
            self.port3.port.get_logical_port().ip
        )
        self.assertEqual(
            netaddr.IPAddress(dst_ip),
            self.port1.port.get_logical_port().ip
        )

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

    def _icmp_ping_pong(self):
        # the rules of the initial security group associated with port3
        # only let icmp echo requests from port1 pass.

        self._update_policy()
        self._create_allowed_address_pairs_policy()
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
            self.permit_port_id = self.port1.port_id
            self.no_permit_port_id = self.port2.port_id

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
            self.permit_port_id = self.port1.port_id
            self.no_permit_port_id = self.port2.port_id

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


class TestPortSecApp(test_base.DFTestBase):
    def setUp(self):
        super(TestPortSecApp, self).setUp()
        self.topology = None
        self.policy = None
        self._ping = None
        self.icmp_id_cursor = int(time.mktime(time.gmtime())) & 0xffff
        try:
            self._init_topology()

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

    def _init_topology(self):
        network = netaddr.IPNetwork(self.cidr)
        security_group = self.store(objects.SecGroupTestObj(
            self.neutron,
            self.nb_api))
        security_group_id = security_group.create()
        self.assertTrue(security_group.exists())

        egress_rule_info = {'ethertype': self.ethertype,
                            'direction': 'egress',
                            'protocol': self.icmp_proto}
        egress_rule_id = security_group.rule_create(
            secrule=egress_rule_info)
        self.assertTrue(security_group.rule_exists(egress_rule_id))

        ingress_rule_info = {'ethertype': self.ethertype,
                             'direction': 'ingress',
                             'protocol': self.icmp_proto,
                             'remote_ip_prefix': self.cidr}
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
            cidr=self.cidr
        )
        self.port1 = self.subnet.create_port()
        self.port1.update({
            "allowed_address_pairs": [
                {"ip_address": network[100],
                 "mac_address": "10:20:99:99:99:99"}
            ]
        })
        self.port2 = self.subnet.create_port([security_group_id])

    def _get_fake_ip(self):
        if self.ethertype == n_const.IPv4:
            ip = "1.2.3.4"
        else:
            ip = "1::9"
        return ip

    def _get_icmp_packet(self):
        icmp_id = self.icmp_id_cursor & 0xffff
        self.icmp_id_cursor += 1
        icmp_seq = 0
        if self.ethertype == n_const.IPv4:
            icmp = ryu.lib.packet.icmp.icmp(
                type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
                data=ryu.lib.packet.icmp.echo(
                    id_=icmp_id,
                    seq=icmp_seq,
                    data=self._create_random_string())
            )
        else:
            icmp = ryu.lib.packet.icmpv6.icmpv6(
                type_=ryu.lib.packet.icmpv6.ICMPV6_ECHO_REQUEST,
                data=ryu.lib.packet.icmpv6.echo(
                    id_=icmp_id,
                    seq=icmp_seq,
                    data=self._create_random_string())
            )
        return icmp

    def _get_packet_protocol(self, src_ip, dst_ip):
        if self.ethertype == n_const.IPv4:
            ip = ryu.lib.packet.ipv4.ipv4(
                src=str(src_ip),
                dst=str(dst_ip),
                proto=ryu.lib.packet.ipv4.inet.IPPROTO_ICMP,
            )
        else:
            ip = ryu.lib.packet.ipv6.ipv6(
                src=str(src_ip),
                dst=str(dst_ip),
                nxt=ryu.lib.packet.ipv6.inet.IPPROTO_ICMPV6)

        return ip

    def _create_ping_request(self, src_ip, src_mac, dst_port):
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=str(src_mac),
            dst=str(dst_port.port.get_logical_port().mac),
            ethertype=self.ethtype
        )

        ip = self._get_packet_protocol(
            src_ip,
            dst_port.port.get_logical_port().ip)
        icmp = self._get_icmp_packet()
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result, icmp

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
                    self._get_ping_using_vm_ip_mac, self.ethertype),
                actions=[
                    count_action,
                    app_testing_objects.DisableRuleAction(),
                ]
            ),
            app_testing_objects.PortPolicyRule(
                app_testing_objects.RyuICMPPingFilter(
                    self._get_ping_using_allowed_address_pair_ip_mac,
                    self.ethertype),
                actions=[
                    count_action,
                    app_testing_objects.DisableRuleAction(),
                ]
            ),
            app_testing_objects.PortPolicyRule(
                app_testing_objects.RyuICMPPingFilter(
                    self._get_ping_using_fake_ip, self.ethertype),
                actions=[
                    app_testing_objects.RaiseAction("a packet with a fake "
                                                    "ip passed")
                ]
            ),
            app_testing_objects.PortPolicyRule(
                app_testing_objects.RyuICMPPingFilter(
                    self._get_ping_using_fake_mac, self.ethertype),
                actions=[
                    app_testing_objects.RaiseAction("a packet with a fake "
                                                    "mac passed")
                ]
            )
        ]
        rules += self._get_filtering_rules()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        policy = app_testing_objects.PortPolicy(
            rules=rules,
            default_action=raise_action
        )

        return {
            key: policy
        }

    def _create_ping_using_vm_ip_mac(self, buf):
        ip = self.port1.port.get_logical_port().ip
        mac = self.port1.port.get_logical_port().mac

        result, icmp = self._create_ping_request(ip, mac, self.port2)
        self._ping_using_vm_ip_mac = icmp
        return result.data

    def _create_ping_using_allowed_address_pair(self, buf):
        pairs = self.port1.port.get_logical_port().allowed_address_pairs
        ip = pairs[0].ip_address
        mac = pairs[0].mac_address

        result, icmp = self._create_ping_request(ip, mac, self.port2)
        self._ping_using_allowed_address_pair = icmp
        return result.data

    def _create_ping_using_fake_ip(self, buf):
        fake_ip = self._get_fake_ip()
        mac = self.port1.port.get_logical_port().mac

        result, icmp = self._create_ping_request(fake_ip, mac, self.port2)
        self._ping_using_fake_ip = icmp
        return result.data

    def _create_ping_using_fake_mac(self, buf):
        ip = self.port1.port.get_logical_port().ip
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


class TestPortSecAppV4(TestPortSecApp):
    def setUp(self):
        self.topology = None
        self.policy = None
        self._ping = None
        self.icmp_id_cursor = int(time.mktime(time.gmtime())) & 0xffff
        self.cidr = "192.168.196.0/24"
        self.ethertype = n_const.IPv4
        self.icmp_proto = "icmp"
        self.ethtype = ryu.lib.packet.ethernet.ether.ETH_TYPE_IP
        super(TestPortSecAppV4, self).setUp()

    def test_icmp_ping_using_different_ip_mac(self):
        self.policy.start(self.topology)
        self.policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(self.policy.exceptions) > 0:
            raise self.policy.exceptions[0]


class TestPortSecAppV6(TestPortSecApp):
    def setUp(self):
        self.topology = None
        self.policy = None
        self._ping = None
        self.icmp_id_cursor = int(time.mktime(time.gmtime())) & 0xffff
        self.cidr = "fda8:06c3:ce53:a890::1/32"
        self.ethertype = n_const.IPv6
        self.ethtype = ryu.lib.packet.ethernet.ether.ETH_TYPE_IPV6
        self.icmp_proto = "icmpv6"
        super(TestPortSecAppV6, self).setUp()

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
        if not self.check_app_loaded("active_port_detection"):
            self.skipTest("ActivePortDetectionApp is not enabled")
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

            allowed_address_pairs = port_lport.allowed_address_pairs
            self.assertIsNotNone(allowed_address_pairs)

            self.allowed_address_pair_ip_address = \
                allowed_address_pairs[0].ip_address
            self.allowed_address_pair_mac_address = \
                allowed_address_pairs[0].mac_address

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
            str(self.allowed_address_pair_ip_address)
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
        if lport.topic != active_port.topic:
            return False
        if lport.id != active_port.detected_lport.id:
            return False
        if lport.lswitch.id != active_port.network.id:
            return False
        if self.allowed_address_pair_ip_address != active_port.ip:
            return False
        if self.allowed_address_pair_mac_address != active_port.detected_mac:
            return False
        return True

    def _if_the_expected_active_port_exists(self):
        active_ports = self.nb_api.get_all(
                active_port.AllowedAddressPairsActivePort)
        for port in active_ports:
            if self._is_expected_active_port(port):
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
            src=str(self.port.port.get_logical_port().mac),
            dst=str(router_interface_port['port']['mac_address']),
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=str(self.port.port.get_logical_port().ip),
            dst=str(dst_ip),
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
                        initial_packet,
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
            initial_packet)
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
                        initial_packet,
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
            initial_packet)
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
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

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

        src_mac = ether.dst
        dst_mac = ether.src
        ether.src = src_mac
        ether.dst = dst_mac
        self.assertEqual(
            src_mac,
            str(self.vlan_port2.get_logical_port().mac)
        )
        self.assertEqual(
            dst_mac,
            str(self.vlan_port1.get_logical_port().mac)
        )

        src_ip = ip.dst
        dst_ip = ip.src
        ip.src = src_ip
        ip.dst = dst_ip
        self.assertEqual(
            netaddr.IPAddress(src_ip),
            self.vlan_port2.get_logical_port().ip
        )
        self.assertEqual(
            netaddr.IPAddress(dst_ip),
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


class TestSNat(test_base.DFTestBase):
    namespace_name = 'test-snat'
    iface0_name = 'snat_veth0'
    iface1_name = 'snat_veth1'

    def setUp(self):
        super(TestSNat, self).setUp()
        ipwrapper = ip_lib.IPWrapper()
        snat_veth0_device, snat_veth1_device = ipwrapper.add_veth(
                                    self.iface0_name,
                                    self.iface1_name, self.namespace_name)

        snat_veth1_device.link.set_up()
        snat_veth1_device.addr.add('10.0.1.2/30')

        snat_veth0_device.link.set_up()
        snat_veth0_device.addr.add('10.0.1.1/30')

        snat_veth1_device.route.add_gateway('10.0.1.1')

        time.sleep(10)

    def tearDown(self):
        ipwrapper = ip_lib.IPWrapper()
        ipwrapper.del_veth(self.iface0_name)
        ipwrapper.netns.delete(self.namespace_name)
        super(TestSNat, self).tearDown()

    def test_icmp_ping_pong_with_external_peer(self):
        self._create_topology()
        policy = self._create_policy()
        policy.start(self.topology)
        policy.wait(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]

    def _create_topology(self):
        self.topology = self.store(
            app_testing_objects.Topology(
                self.neutron,
                self.nb_api
            )
        )
        self.subnet1 = self.topology.create_subnet(cidr='192.168.15.0/24')
        self.port1 = self.subnet1.create_port()
        self.router = self.topology.create_router([self.subnet1.subnet_id])
        self.topology.create_external_network([self.router.router_id])
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

    def _create_policy(self):
        port_policies = self._create_port_policies()
        initial_packet = self._create_packet(
            '10.0.1.2', ryu.lib.packet.ipv4.inet.IPPROTO_ICMP)
        policy = self.store(
            app_testing_objects.Policy(
                initial_actions=[
                    app_testing_objects.SendAction(
                        self.subnet1.subnet_id,
                        self.port1.port_id,
                        initial_packet
                    ),
                ],
                port_policies=port_policies,
                unknown_port_action=app_testing_objects.IgnoreAction()
            )
        )
        return policy

    def _create_port_policies(self):
        ignore_action = app_testing_objects.IgnoreAction()
        raise_action = app_testing_objects.RaiseAction("Unexpected packet")
        key1 = (self.subnet1.subnet_id, self.port1.port_id)
        actions = [app_testing_objects.DisableRuleAction(),
                   app_testing_objects.StopSimulationAction()]
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
        policy1 = app_testing_objects.PortPolicy(
            rules=rules1,
            default_action=raise_action
        )
        return {
            key1: policy1,
        }

    def _create_packet(self, dst_ip, proto, ttl=255):
        router_interface = self.router.router_interfaces[
            self.subnet1.subnet_id
        ]
        router_interface_port = self.neutron.show_port(
            router_interface['port_id']
        )
        ethernet = ryu.lib.packet.ethernet.ethernet(
            src=self.port1.port.get_logical_port().mac,
            dst=router_interface_port['port']['mac_address'],
            ethertype=ryu.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = ryu.lib.packet.ipv4.ipv4(
            src=self.port1.port.get_logical_port().ip,
            dst=dst_ip,
            ttl=ttl,
            proto=proto,
        )
        ip_data = ryu.lib.packet.icmp.icmp(
            type_=ryu.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=ryu.lib.packet.icmp.echo(
                data=self._create_random_string())
        )
        self._ping = ip_data
        self._ip = ip
        result = ryu.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(ip_data)
        result.serialize()
        return result.data

    def _get_ping(self):
        return self._ping
