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

from oslo_log import log
import ryu.lib.packet

from dragonflow import conf as cfg
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


class TestDNATApp(test_base.DFTestBase):
    def setUp(self):
        super(TestDNATApp, self).setUp()

        self.topology = None
        self.topology = app_testing_objects.Topology(self.neutron,
                                                     self.nb_api)
        self.addCleanup(self.topology.close)
        self.subnet = self.topology.create_subnet()
        self.port = self.subnet.create_port()
        self.router = self.topology.create_router([
            self.subnet.subnet_id
        ])
        ext_net_id = self.topology.create_external_network([
            self.router.router_id
        ])
        self.fip = objects.FloatingipTestObj(self.neutron, self.nb_api)
        self.addCleanup(self.fip.close)
        self.fip.create({'floating_network_id': ext_net_id,
                         'port_id': self.port.port.port_id})

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
        policy = app_testing_objects.Policy(
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
        self.addCleanup(policy.close)
        apps.start_policy(policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

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
        policy = app_testing_objects.Policy(
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
        self.addCleanup(policy.close)
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
        policy = app_testing_objects.Policy(
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
        self.addCleanup(policy.close)
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
        policy = app_testing_objects.Policy(
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
        self.addCleanup(policy.close)
        policy.start(self.topology)
        # Since the rate limit, we expect timeout to wait for 4th packet hit
        # the policy.
        self.assertRaises(
            app_testing_objects.TimeoutException,
            policy.wait,
            const.DEFAULT_RESOURCE_READY_TIMEOUT)
        if len(policy.exceptions) > 0:
            raise policy.exceptions[0]
