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
import os_ken.lib.packet
from oslo_log import log

from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


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
                        app_testing_objects.OsKenVLANTagFilter(7),
                        app_testing_objects.OsKenICMPPongFilter(
                            self._get_ping)),
                actions=[app_testing_objects.DisableRuleAction(),
                         app_testing_objects.StopSimulationAction()]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.OsKenARPGratuitousFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 packets
                app_testing_objects.OsKenIPv6Filter(),
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
                        app_testing_objects.OsKenVLANTagFilter(8),
                        app_testing_objects.OsKenICMPPingFilter()),
                actions=[app_testing_objects.SendAction(
                                self.subnet1.subnet_id,
                                self.port2.port_id,
                                self._create_pong_packet),
                         app_testing_objects.DisableRuleAction()]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore gratuitous ARP packets
                app_testing_objects.OsKenARPGratuitousFilter(),
                actions=[
                    ignore_action
                ]
            ),
            app_testing_objects.PortPolicyRule(
                # Ignore IPv6 packets
                app_testing_objects.OsKenIPv6Filter(),
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
        ethernet = os_ken.lib.packet.ethernet.ethernet(
            src=self.vlan_port1.get_logical_port().mac,
            dst=self.vlan_port2.get_logical_port().mac,
            ethertype=os_ken.lib.packet.ethernet.ether.ETH_TYPE_8021Q,
        )
        vlan = os_ken.lib.packet.vlan.vlan(
            vid=7,
            ethertype=os_ken.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = os_ken.lib.packet.ipv4.ipv4(
            src=str(self.vlan_port1.get_logical_port().ip),
            dst=str(self.vlan_port2.get_logical_port().ip),
            ttl=ttl,
            proto=os_ken.lib.packet.ipv4.inet.IPPROTO_ICMP,
        )
        ip_data = os_ken.lib.packet.icmp.icmp(
            type_=os_ken.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=os_ken.lib.packet.icmp.echo(
                data=self._create_random_string())
        )
        self._ping = ip_data
        result = os_ken.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(vlan)
        result.add_protocol(ip)
        result.add_protocol(ip_data)
        result.serialize()
        return result.data

    def _create_pong_packet(self, buf):
        pkt = os_ken.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(os_ken.lib.packet.ethernet.ethernet)
        vlan = pkt.get_protocol(os_ken.lib.packet.vlan.vlan)
        ip = pkt.get_protocol(os_ken.lib.packet.ipv4.ipv4)
        icmp = pkt.get_protocol(os_ken.lib.packet.icmp.icmp)

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

        icmp.type = os_ken.lib.packet.icmp.ICMP_ECHO_REPLY
        icmp.csum = 0
        result = os_ken.lib.packet.packet.Packet()
        result.add_protocol(ether)
        result.add_protocol(vlan)
        result.add_protocol(ip)
        result.add_protocol(icmp)
        result.serialize()
        return result.data
