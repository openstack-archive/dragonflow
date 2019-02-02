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

import os_ken.lib.packet
from oslo_log import log

from dragonflow.db.models import active_port
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import apps
from dragonflow.tests.fullstack import test_base

LOG = log.getLogger(__name__)


class TestAllowedAddressPairsDetectActive(test_base.DFTestBase):

    def _create_policy_to_reply_arp_request(self):
        ignore_action = app_testing_objects.IgnoreAction()
        key1 = (self.subnet.subnet_id, self.port.port_id)
        port_policies = {
            key1: app_testing_objects.PortPolicy(
                rules=[
                    app_testing_objects.PortPolicyRule(
                        # Detect arp requests
                        app_testing_objects.OsKenARPRequestFilter(
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
        self.topology = app_testing_objects.Topology(self.neutron,
                                                     self.nb_api)
        self.addCleanup(self.topology.close)
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

        self.allowed_address_pair_mac_address, \
            self.allowed_address_pair_ip_address = \
            apps.get_port_mac_and_ip(port, True)

        # Create policy to reply arp request sent from controller
        self.policy = app_testing_objects.Policy(
            initial_actions=[],
            port_policies=self._create_policy_to_reply_arp_request(),
            unknown_port_action=app_testing_objects.IgnoreAction()
        )
        self.addCleanup(self.policy.close)

    def _create_arp_response(self, buf):
        pkt = os_ken.lib.packet.packet.Packet(buf)
        ether = pkt.get_protocol(os_ken.lib.packet.ethernet.ethernet)
        arp = pkt.get_protocol(os_ken.lib.packet.arp.arp)

        ether.src, ether.dst = self.allowed_address_pair_mac_address, ether.src

        self.assertEqual(
            arp.dst_ip,
            str(self.allowed_address_pair_ip_address)
        )
        arp_sha = self.allowed_address_pair_mac_address
        arp_spa = self.allowed_address_pair_ip_address
        arp_tha = arp.src_mac
        arp_tpa = arp.src_ip
        arp.opcode = os_ken.lib.packet.arp.ARP_REPLY
        arp.src_mac = arp_sha
        arp.src_ip = arp_spa
        arp.dst_mac = arp_tha
        arp.dst_ip = arp_tpa

        result = os_ken.lib.packet.packet.Packet()
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
        apps.start_policy(self.policy, self.topology, 30)

        # check if the active port exists in DF DB
        self.assertTrue(self._if_the_expected_active_port_exists())

        # clear allowed address pairs configuration from the lport
        self.port.update({'allowed_address_pairs': []})
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # check if the active port was removed from DF DB
        self.assertFalse(self._if_the_expected_active_port_exists())
