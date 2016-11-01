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

import random

from dragonflow.controller.common import constants as const
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.common import constants as test_const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base


class TestL3Flows(test_base.DFTestBase):
    def setUp(self):
        super(TestL3Flows, self).setUp()
        self.topology = None
        try:
            self.topology = app_testing_objects.Topology(
                self.neutron,
                self.nb_api)
            self.subnet1 = self.topology.create_subnet(cidr='192.168.10.0/24')
            self.port1 = self.subnet1.create_port()
            self.router = self.topology.create_router([
                self.subnet1.subnet_id])

        except Exception:
            if self.topology:
                self.topology.close()
            raise
        self.store(self.topology)

    def test_router_add_route(self):
        lport = self.port1.port.get_logical_port()
        ip1 = lport.get_ip()
        dest = "10.{}.{}.0/24".format(
            random.randint(0, 254), random.randint(0, 254))
        body = {
                    "routes": [
                        {
                            "nexthop": ip1,
                            "destination": dest
                        }
                    ]
                }
        self.neutron.update_router(self.router.router.router_id,
                                   body={'router': body})

        # table = 20, priority = 100, ip, nw_src = 192.168.10.0/24,
        # nw_dst = 10.110.10.0/24
        # actions = dec_ttl, load:0x18->NXM_NX_REG7[], resubmit(, 64)
        utils.wait_until_true(
            lambda: any(self._get_route_flows('192.168.10.0/24',
                                              dest)),
            timeout=test_const.DEFAULT_RESOURCE_READY_TIMEOUT,
            exception=Exception('route flow entry is not installed')
        )
        body['routes'] = []
        self.neutron.update_router(self.router.router.router_id,
                                   body={'router': body})

        utils.wait_until_true(
            lambda: not any(self._get_route_flows('192.168.10.0/24',
                                                  dest)),
            timeout=test_const.DEFAULT_RESOURCE_READY_TIMEOUT,
            exception=Exception('route flow entry is not deleted')
        )

    def _get_route_flows(self, nw_src, nw_dst):
        match = 'nw_src=' + nw_src + ',nw_dst=' + nw_dst
        ovs_flows_parser = utils.OvsFlowsParser()
        flows = ovs_flows_parser.dump(self.integration_bridge)
        flows = [flow for flow in flows
                 if flow['table'] == str(const.L3_LOOKUP_TABLE) and
                 flow['priority'] == str(const.PRIORITY_VERY_HIGH) and
                 (match in flow['match'])]
        return flows
