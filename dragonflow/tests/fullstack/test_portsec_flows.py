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

from dragonflow.controller.common import constants as const
from dragonflow.tests.common import constants as test_const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestOVSFlowsForPortSecurity(test_base.DFTestBase):

    def _is_expected_flow(self, flow, expected_list):
        if flow['table'] != str(const.EGRESS_PORT_SECURITY_TABLE):
            return False

        priority = expected_list['priority']
        if flow['priority'] != priority:
            return False

        match_list = expected_list['match_list']
        for expected_match in match_list:
            if expected_match not in flow['match']:
                return False

        actions = expected_list['actions']
        if flow['actions'] != actions:
            return False

        return True

    def _get_ip_match(self, ip):
        ip_version = netaddr.IPAddress(ip).version
        if ip_version == n_const.IP_VERSION_4:
            return "nw_src=" + str(ip)
        else:
            return "ipv6_src=" + str(ip)

    def _get_eth_match(self, ip):
        ip_version = netaddr.IPAddress(ip).version
        if ip_version == n_const.IP_VERSION_4:
            return "ip"
        else:
            return "ipv6"

    def _get_anti_spoof_expected_flows(self, ip, mac, unique_key):
        expected_flow_list = []
        ip_version = netaddr.IPAddress(ip).version

        unique_key_match = "reg6=" + hex(unique_key)
        dl_src_match = "dl_src=" + mac
        goto_conntrack_table_action = \
            "goto_table:" + str(const.EGRESS_CONNTRACK_TABLE)
        goto_classification_table_action = \
            "goto_table:" + str(const.SERVICES_CLASSIFICATION_TABLE)

        # priority: High, match: reg6=unique_key, dl_src=$vm_mac,
        # dl_dst=ff:ff:ff:ff:ff:ff, udp, tp_src=68, tp_dst=67,
        # actions: goto const.EGRESS_CONNTRACK_TABLE
        dl_dst_match = "dl_dst=" + const.BROADCAST_MAC
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": [unique_key_match, dl_src_match, dl_dst_match,
                           "udp", "tp_src=" + str(const.DHCP_CLIENT_PORT),
                           "tp_dst=" + str(const.DHCP_SERVER_PORT)],
            "actions": goto_conntrack_table_action
        })

        # conntrack_flow_match = self._get_conntrack_flow_match(ip)
        eth_match_item = self._get_eth_match(ip)
        ip_match = self._get_ip_match(ip)
        # priority: High, match: ip/ipv6, reg6=unique_key, dl_src=$vm_mac,
        # nw_src=$fixed_ip/ipv6_src=$fixed_ip,
        # actions: goto const.EGRESS_CONNTRACK_TABLE
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": [eth_match_item, unique_key_match, dl_src_match,
                           ip_match],
            "actions": goto_conntrack_table_action
        })

        if ip_version == n_const.IP_VERSION_4:
            # priority: High, match: arp, reg6=unique_key, dl_src=$vm_mac,
            # arp_spa=$fixed_ip, arp_sha=$vm_mac
            # actions: goto const.SERVICES_CLASSIFICATION_TABLE
            arp_spa_match = "arp_spa=" + ip
            arp_sha_match = "arp_sha=" + mac
            expected_flow_list.append({
                "priority": str(const.PRIORITY_HIGH),
                "match_list": ["arp", unique_key_match, dl_src_match,
                               arp_spa_match, arp_sha_match],
                "actions": goto_classification_table_action
            })

            # priority: High, match: arp, reg6=unique_key, dl_src=$vm_mac,
            # arp_op=1, arp_spa=0, arp_sha=$vm_mac
            # actions: goto const.SERVICES_CLASSIFICATION_TABLE
            arp_sha_match = "arp_sha=" + mac
            expected_flow_list.append({
                "priority": str(const.PRIORITY_HIGH),
                "match_list": ["arp", unique_key_match, dl_src_match,
                               "arp_spa=0.0.0.0", "arp_op=1", arp_sha_match],
                "actions": goto_classification_table_action
            })
        else:
            # priority: High, match: icmp6, reg6=unique_key,
            # dl_src=$vm_mac, ipv6_src=$fixed_ip
            # actions: goto const.SERVICES_CLASSIFICATION_TABLE
            ipv6_ip_match = "ipv6_src=" + ip
            expected_flow_list.append({
                "priority": str(const.PRIORITY_HIGH),
                "match_list": ["icmp6", unique_key_match, dl_src_match,
                               ipv6_ip_match],
                "actions": goto_classification_table_action
            })

        # priority: Low, match: reg6=unique_key, dl_src=$vm_mac
        # actions: goto const.SERVICES_CLASSIFICATION_TABLE
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": [unique_key_match, dl_src_match],
            "actions": goto_classification_table_action
        })

        return expected_flow_list

    def _check_all_flows_existed(self, expected_flow_list):
        ovs = utils.OvsFlowsParser()
        flows = ovs.dump(self.integration_bridge)

        for flow in flows:
            for expected_flow in expected_flow_list:
                if expected_flow.get("aleady_found"):
                    continue
                if self._is_expected_flow(flow, expected_flow):
                    expected_flow["aleady_found"] = True

        for expected_flow in expected_flow_list:
            if not expected_flow.get("aleady_found"):
                # for knowing which flow didn't be installed when the test
                # case failed, asserting expected_flow equals to None to print
                # expected_flow
                self.assertIsNone(expected_flow)

    def _check_not_flow_existed(self, flow_list):
        ovs = utils.OvsFlowsParser()
        flows = ovs.dump(self.integration_bridge)

        for flow in flows:
            for expected_flow in flow_list:
                if self._is_expected_flow(flow, expected_flow):
                    # for knowing which flow didn't be removed when the
                    # test case failed, asserting expected_flow equals to
                    # None to print expected_flow
                    self.assertIsNone(expected_flow)

    def test_default_flows(self):
        expected_flow_list = []

        # priority: medium, match: ip, actions: drop
        expected_flow_list.append({
            "priority": str(const.PRIORITY_MEDIUM),
            "match_list": ["ip"],
            "actions": "drop"
        })

        # priority: medium, match: arp, actions: drop
        expected_flow_list.append({
            "priority": str(const.PRIORITY_MEDIUM),
            "match_list": ["arp"],
            "actions": "drop"
        })

        # priority: medium, match: ipv6, actions: drop
        expected_flow_list.append({
            "priority": str(const.PRIORITY_MEDIUM),
            "match_list": ["ip"],
            "actions": "drop"
        })

        # priority: very low, actions: drop
        expected_flow_list.append({
            "priority": str(const.PRIORITY_VERY_LOW),
            "match_list": [],
            "actions": "drop"
        })

        # priority: very low, actions: drop
        expected_flow_list.append({
            "priority": str(const.PRIORITY_VERY_LOW),
            "match_list": [],
            "actions": "drop"
        })

        # priority: default, goto const.EGRESS_CONNTRACK_TABLE
        expected_flow_list.append({
            "priority": str(const.PRIORITY_DEFAULT),
            "match_list": [],
            "actions": "goto_table:" + str(const.EGRESS_CONNTRACK_TABLE)
        })

        self._check_all_flows_existed(expected_flow_list)

    def _test_anti_spoof_flows(self, subnet_info):

        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        self.assertTrue(network.exists())

        subnet_info['network_id'] = network_id
        subnet = self.store(objects.SubnetTestObj(self.neutron,
                                                  self.nb_api,
                                                  network_id=network_id))
        subnet.create(subnet_info)
        self.assertTrue(subnet.exists())

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)

        addresses = vm.server.addresses['mynetwork']
        self.assertIsNotNone(addresses)
        ip = addresses[0]['addr']
        self.assertIsNotNone(ip)
        mac = addresses[0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)
        port = utils.wait_until_is_and_return(
            lambda: utils.find_logical_port(self.nb_api, ip, mac),
            exception=Exception('No port assigned to VM')
        )

        of_port = self.vswitch_api.get_port_ofport_by_id(port.id)
        self.assertIsNotNone(of_port)
        unique_key = port.unique_key

        # Check if the associating flows were installed.
        expected_flow_list = self._get_anti_spoof_expected_flows(
            ip, mac, unique_key
        )
        self._check_all_flows_existed(expected_flow_list)

        vm.close()

        time.sleep(test_const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # Check if the associating flows were removed.
        expected_flow_list = self._get_anti_spoof_expected_flows(
            ip, mac, unique_key
        )
        self._check_not_flow_existed(expected_flow_list)

    def test_anti_spoof_flows_ipv4(self):
        subnet_info = {
                       'cidr': '192.168.130.0/24',
                       'gateway_ip': '192.168.130.1',
                       'ip_version': 4,
                       'name': 'test_subnet1',
                       'enable_dhcp': True}
        self._test_anti_spoof_flows(subnet_info)

    def test_anti_spoof_flows_ipv6(self):
        subnet_info = {
                       'cidr': '1111:1111:1111::/64',
                       'gateway_ip': '1111:1111:1111::1',
                       'ip_version': 6,
                       'name': 'test_subnet1',
                       'enable_dhcp': True}
        self._test_anti_spoof_flows(subnet_info)
