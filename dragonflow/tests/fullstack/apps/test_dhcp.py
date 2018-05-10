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

import struct
import time

from oslo_log import log
import ryu.lib.packet
from ryu.lib.packet import dhcp

from dragonflow.controller.common import constants
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.common import utils as test_utils
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base

LOG = log.getLogger(__name__)


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
            if (int(flow['table']) == self.dfdp.apps['dhcp'].states.main and
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
        apps.start_policy(policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

    def test_disable_enable_dhcp(self):
        self._create_topology(enable_dhcp=False)
        self._test_disable_dhcp()
        self.subnet1.update({'enable_dhcp': True})
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        self._test_enable_dhcp()
