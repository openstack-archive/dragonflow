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

from neutron.agent.common import utils

from dragonflow.tests.fullstack import test_base

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

    def _parse_ovs_flows(self):
        flows = self._get_ovs_flows()
        flow_list = flows.split("\n")[1:]
        flows_as_dicts = []
        for flow in flow_list:
            fs = flow.split(' ')
            res = {}
            res['table'] = fs[3].split('=')[1]
            res['match'] = fs[6]
            res['packets'] = fs[4].split('=')[1]
            res['actions'] = fs[7].split('=')[1]
            res['cookie'] = fs[1].split('=')[1]
            flows_as_dicts.append(res)
        return flows_as_dicts
