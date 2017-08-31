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
import time

from neutron.agent.common import utils
from oslo_log import log
import ryu.lib.packet
import testtools

from dragonflow import conf as cfg
from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


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

        ether.src, ether.dst = ether.dst, ether.src

        lport2 = self.port2.port.get_logical_port()
        self.assertIn(
            ether.src,
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
            ether.dst,
            router_mac,
        )

        ip.src, ip.dst = ip.dst, ip.src
        self.assertIn(
            netaddr.IPAddress(ip.src),
            lport2.ips + [
                p.ip_address for p in lport2.allowed_address_pairs or ()
            ]
        )
        self.assertEqual(
            netaddr.IPAddress(ip.dst),
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
        apps.start_policy(policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

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
        time.sleep(apps.CONTROLLER_RECONNECT_TIMEOUT)
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
        apps.start_policy(policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

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
        apps.start_policy(policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

