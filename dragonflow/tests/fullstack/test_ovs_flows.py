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
from neutron.agent.common import utils

from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

EXPECTED_NUMBER_OF_FLOWS_AFTER_GATE_DEVSTACK = 26

class TestOVSFlows(test_base.DFTestBase):

    def setUp(self):
        super(TestOVSFlows, self).setUp()

    def _get_ovs_flows(self):
        full_args = ["ovs-ofctl", "dump-flows", 'br-int', '-O Openflow13']
        flows = utils.execute(full_args, run_as_root=True,
                              process_input=None)
        return flows

    def test_number_of_flows(self):
        flows = self._get_ovs_flows()
        flow_list = flows.split("\n")[1:]
        flows_count = len(flow_list) - 1
        self.assertEqual(flows_count,
                         EXPECTED_NUMBER_OF_FLOWS_AFTER_GATE_DEVSTACK)

    def _parse_ovs_flows(self, flows):
        flow_list = flows.split("\n")[1:]
        flows_as_dicts = []
        for flow in flow_list:
            if len(flow) == 0:
                continue
            fs = flow.split(' ')
            res = {}
            res['table'] = fs[3].split('=')[1]
            res['match'] = fs[-2]
            res['match'] = fs[6]
            # no need for number of packets for now
            #res['packets'] = fs[4].split('=')[1]
            res['actions'] = fs[-1].split('=')[1]
            res['cookie'] = fs[1].split('=')[1]
            m = re.search('priority=(\d+)', res['match'])
            if m:
                res['priority'] = m.group(1)
                res['match'] = re.sub(r'priority=(\d+),?', '', res['match'])
            flows_as_dicts.append(res)
        return flows_as_dicts

    def _diff_flows(self, list1, list2):
        result = [v for v in list2 if v not in list1]
        return result

    def test_dhcp_port_created(self):
        flows1 = self._get_ovs_flows()
        flows1 = self._parse_ovs_flows(flows1)
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.1.0.0/24',
            'gateway_ip': '10.1.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        self.neutron.create_subnet({'subnet': subnet})
        flows2 = self._get_ovs_flows()
        flows2 = self._parse_ovs_flows(flows2)
        diff = self._diff_flows(flows1, flows2)
        # we must have only one new row
        self.assertEqual(len(diff), 1)
        diff = diff[0]
        self.assertEqual(diff['table'], '9,')
        self.assertEqual(diff['actions'], 'goto_table:11')
        if 'nw_dst=10.1.0.2' not in diff['match']:
            self.assertFalse(None)
        network.delete()
        flows3 = self._get_ovs_flows()
        flows3 = self._parse_ovs_flows(flows3)
        self.assertEqual(flows1, flows3)

'''
    def test_create_port(self):
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        port = {'admin_state_up': True, 'name': 'port1',
                'network_id': network_id}
        port = self.neutron.create_port(body={'port': port})
        port2 = self.nb_api.get_logical_port(port['port']['id'])
        self.assertIsNotNone(port2)
        self.assertEqual(network_id, port2.get_lswitch_id())
        time.sleep(30)
        self.neutron.delete_port(port['port']['id'])
        port2 = self.nb_api.get_logical_port(port['port']['id'])
        self.assertIsNone(port2)
        network.delete()
        self.assertFalse(network.exists())
'''
