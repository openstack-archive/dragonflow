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

import time

from neutron.agent.common import ip_lib
from neutron.conf.agent import common as n_common
import os_ken.lib.packet
from oslo_log import log

from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base

LOG = log.getLogger(__name__)


class TestSNat(test_base.DFTestBase):
    namespace_name = 'test-snat'
    iface0_name = 'snat_veth0'
    iface1_name = 'snat_veth1'

    def setUp(self):
        super(TestSNat, self).setUp()
        n_common.setup_privsep()
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
        apps.start_policy(policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)

    def _create_topology(self):
        self.topology = app_testing_objects.Topology(self.neutron, self.nb_api)
        self.addCleanup(self.topology.close)
        self.subnet1 = self.topology.create_subnet(cidr='192.168.15.0/24')
        self.port1 = self.subnet1.create_port()
        self.router = self.topology.create_router([self.subnet1.subnet_id])
        self.topology.create_external_network([self.router.router_id])
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

    def _create_policy(self):
        port_policies = self._create_port_policies()
        initial_packet = self._create_packet(
            '10.0.1.2', os_ken.lib.packet.ipv4.inet.IPPROTO_ICMP)
        policy = app_testing_objects.Policy(
            initial_actions=[
                app_testing_objects.SendAction(self.subnet1.subnet_id,
                                               self.port1.port_id,
                                               initial_packet),
            ],
            port_policies=port_policies,
            unknown_port_action=app_testing_objects.IgnoreAction()
        )
        self.addCleanup(policy.close)
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
                app_testing_objects.OsKenICMPPongFilter(self._get_ping),
                actions=actions
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
        ethernet = os_ken.lib.packet.ethernet.ethernet(
            src=self.port1.port.get_logical_port().mac,
            dst=router_interface_port['port']['mac_address'],
            ethertype=os_ken.lib.packet.ethernet.ether.ETH_TYPE_IP,
        )
        ip = os_ken.lib.packet.ipv4.ipv4(
            src=self.port1.port.get_logical_port().ip,
            dst=dst_ip,
            ttl=ttl,
            proto=proto,
        )
        ip_data = os_ken.lib.packet.icmp.icmp(
            type_=os_ken.lib.packet.icmp.ICMP_ECHO_REQUEST,
            data=os_ken.lib.packet.icmp.echo(
                data=self._create_random_string())
        )
        self._ping = ip_data
        self._ip = ip
        result = os_ken.lib.packet.packet.Packet()
        result.add_protocol(ethernet)
        result.add_protocol(ip)
        result.add_protocol(ip_data)
        result.serialize()
        return result.data

    def _get_ping(self):
        return self._ping
