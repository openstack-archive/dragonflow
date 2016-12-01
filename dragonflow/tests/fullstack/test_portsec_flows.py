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

    def _get_vm_port(self, ip, mac):
        ports = self.nb_api.get_all_logical_ports()
        for port in ports:
            if port.get_device_owner() == 'compute:None':
                if port.get_ip() == ip and port.get_mac() == mac:
                    return port
        return None

    def _get_anti_spoof_expected_flows(self, ip, mac, of_port):
        expected_flow_list = []

        in_port_match = "in_port=" + of_port
        dl_src_match = "dl_src=" + mac
        goto_conntrack_table_action = \
            "goto_table:" + str(const.EGRESS_CONNTRACK_TABLE)
        goto_classification_table_action = \
            "goto_table:" + str(const.SERVICES_CLASSIFICATION_TABLE)

        # priority: High, match: in_port=of_port, dl_src=$vm_mac,
        # dl_dst=ff:ff:ff:ff:ff:ff, udp, tp_src=68, tp_dst=67,
        # actions: goto const.EGRESS_CONNTRACK_TABLE
        dl_dst_match = "dl_dst=" + const.BROADCAST_MAC
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": [in_port_match, dl_src_match, dl_dst_match,
                           "udp", "tp_src=" + str(const.DHCP_CLIENT_PORT),
                           "tp_dst=" + str(const.DHCP_SERVER_PORT)],
            "actions": goto_conntrack_table_action
        })

        # priority: High, match: ip, in_port=of_port, dl_src=$vm_mac,
        # nw_src=$fixed_ip,
        # actions: goto const.EGRESS_CONNTRACK_TABLE
        nw_src_match = "nw_src=" + ip
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": ["ip", in_port_match, dl_src_match, nw_src_match],
            "actions": goto_conntrack_table_action
        })

        # priority: High, match: arp, in_port=of_port, dl_src=$vm_mac,
        # arp_spa=$fixed_ip, arp_sha=$vm_mac
        # actions: goto const.SERVICES_CLASSIFICATION_TABLE
        arp_spa_match = "arp_spa=" + ip
        arp_sha_match = "arp_sha=" + mac
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": ["arp", in_port_match, dl_src_match, arp_spa_match,
                           arp_sha_match],
            "actions": goto_classification_table_action
        })

        # priority: High, match: arp, in_port=of_port, dl_src=$vm_mac,
        # arp_op=1, arp_spa=0, arp_sha=$vm_mac
        # actions: goto const.SERVICES_CLASSIFICATION_TABLE
        arp_sha_match = "arp_sha=" + mac
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": ["arp", in_port_match, dl_src_match,
                           "arp_spa=0.0.0.0", "arp_op=1", arp_sha_match],
            "actions": goto_classification_table_action
        })

        # priority: Low, match: in_port=of_port, dl_src=$vm_mac
        # actions: goto const.SERVICES_CLASSIFICATION_TABLE
        expected_flow_list.append({
            "priority": str(const.PRIORITY_HIGH),
            "match_list": [in_port_match, dl_src_match],
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

    def test_anti_spoof_flows(self):

        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create(network={'name': 'test_network1'})
        self.assertTrue(network.exists())

        subnet_info = {'network_id': network_id,
                       'cidr': '192.168.130.0/24',
                       'gateway_ip': '192.168.130.1',
                       'ip_version': 4,
                       'name': 'test_subnet1',
                       'enable_dhcp': True}
        subnet = self.store(objects.SubnetTestObj(self.neutron,
                                                  self.nb_api,
                                                  network_id=network_id))
        subnet.create(subnet_info)
        self.assertTrue(subnet.exists())

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network)

        addresses = vm.server.addresses['test_network1']
        self.assertIsNotNone(addresses)
        ip = addresses[0]['addr']
        self.assertIsNotNone(ip)
        mac = addresses[0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)
        port = utils.wait_until_is_and_return(
            lambda: self._get_vm_port(ip, mac),
            exception=Exception('No port assigned to VM')
        )

        ovsdb = utils.OvsDBParser()
        of_port = ovsdb.get_ofport(port.get_id())
        self.assertIsNotNone(of_port)

        # Check if the associating flows were installed.
        expected_flow_list = self._get_anti_spoof_expected_flows(
            ip, mac, of_port
        )
        self._check_all_flows_existed(expected_flow_list)

        vm.close()

        time.sleep(test_const.DEFAULT_RESOURCE_READY_TIMEOUT)

        # Check if the associating flows were removed.
        expected_flow_list = self._get_anti_spoof_expected_flows(
            ip, mac, of_port
        )
        self._check_not_flow_existed(expected_flow_list)
