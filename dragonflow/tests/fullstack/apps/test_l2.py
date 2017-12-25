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

from neutron.agent.common import utils
from oslo_log import log
import ryu.lib.packet
from ryu.ofproto import inet

from dragonflow.controller.common import constants
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base

LOG = log.getLogger(__name__)

_CONTROLLER_RECONNECT_TIMEOUT = 10


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
        apps.start_policy(self.policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)


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
        apps.start_policy(self.policy, self.topology,
                          const.DEFAULT_RESOURCE_READY_TIMEOUT)
