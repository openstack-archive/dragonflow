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

import re

import time

from dragonflow.controller.common import constants as const
from dragonflow.tests.common.utils import OvsFlowsParser
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class ArpResponderTest(test_base.DFTestBase):

    def _find_arp_responder_flow_by_ip(self, flows, ip_str):
            for flow in flows:
                match = flow['match']
                if not re.search('\\barp\\b', match):
                    continue
                if not re.search(
                        '\\barp_tpa=%s\\b' % ip_str.replace('.', '\\.'),
                        match):
                    continue
                if not re.search('\\barp_op=1\\b', match):
                    continue
                return flow
            return None

    def _get_arp_table_flows(self):
        ovs_flows_parser = OvsFlowsParser()
        flows = ovs_flows_parser.dump()
        flows = [flow for flow in flows
                if flow['table'] == str(const.ARP_TABLE) + ',']
        return flows

    def _wait_for_flow_removal(self, flows_before, timeout):
        while timeout > 0:
            flows_after = self._get_arp_table_flows()
            if flows_after == flows_before:
                return True
            timeout -= 1
            time.sleep(1)
        return False

    def test_arp_responder(self):
        """
        Add a VM. Verify it's ARP flow is there.
        """
        flows_before = self._get_arp_table_flows()

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create()
        ip = vm.get_first_ipv4()
        self.assertIsNotNone(ip)

        flows_middle = self._get_arp_table_flows()

        vm.server.stop()
        vm.close()
        flows_delta = [flow for flow in flows_middle
                if flow not in flows_before]
        self.assertIsNotNone(
            self._find_arp_responder_flow_by_ip(flows_delta, ip)
        )
        if not self._wait_for_flow_removal(flows_before, 30):
            print 'Flows before and after the test are not the same:'
            print 'Before: ', flows_before
            print 'After: ', self._get_arp_table_flows()
            print 'Verifying we have removed the l2 responder flows.'
            flows_after = self._get_arp_table_flows()
            flows_delta = [flow for flow in flows_after
                    if flow not in flows_before]
            self.assertIsNone(
                self._find_arp_responder_flow_by_ip(flows_delta, ip)
            )
