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
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


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
            self.policy = app_testing_objects.Policy(
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
            self.addCleanup(self.policy.close)
        except Exception:
            if self.topology:
                self.topology.close()
            raise

    def _init_topology(self):
        network = netaddr.IPNetwork(self.cidr)
        security_group = objects.SecGroupTestObj(self.neutron, self.nb_api)
        self.addCleanup(security_group.close)
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
        self.topology = app_testing_objects.Topology(self.neutron,
                                                     self.nb_api)
        self.addCleanup(self.topology.close)

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
        mac, ip = apps.get_port_mac_and_ip(self.port1, True)

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
        apps.start_policy(self.policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)


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
        apps.start_policy(self.policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)
