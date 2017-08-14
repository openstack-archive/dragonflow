# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy
import mock

from dragonflow.controller.common import constants as const
from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.tests.unit import test_app_base


class TestLegacySNatApp(test_app_base.DFAppTestBase):
    apps_list = ["legacy_snat"]

    def setUp(self):
        super(TestLegacySNatApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['legacy_snat']
        mock.patch.object(self.app, '_add_router_port',
                          side_effect=self.app._add_router_port).start()
        mock.patch.object(self.app, '_delete_router_port',
                          side_effect=self.app._delete_router_port).start()
        self.app.mod_flow.reset_mock()

    def test_create_router(self):
        self.subnets = [l2.Subnet(dhcp_ip="10.1.0.2",
                                  name="private-subnet",
                                  enable_dhcp=True,
                                  topic="fake_tenant1",
                                  gateway_ip="10.1.0.1",
                                  cidr="10.1.0.0/24",
                                  id="test_subnet10_1")]
        self.lswitch = l2.LogicalSwitch(subnets=self.subnets,
                                        unique_key=3,
                                        name='test_lswitch_1',
                                        is_external=False,
                                        segmentation_id=41,
                                        topic='fake_tenant1',
                                        id='test_lswitch_1',
                                        version=5)
        self.router_ports = [l3.LogicalRouterPort(network="10.1.0.1/24",
                                                  lswitch=self.lswitch,
                                                  topic="fake_tenant1",
                                                  mac="fa:16:3e:50:96:f5",
                                                  unique_key=4,
                                                  id="fake_router_1_port1")]
        self.router = l3.LogicalRouter(name="fake_router_1",
                                       topic="fake_tenant1",
                                       version=10,
                                       id="fake_router_1",
                                       unique_key=5,
                                       ports=self.router_ports)
        self.controller.update(self.lswitch)
        self.app.mod_flow.reset_mock()
        self.controller.update(self.router)
        self.app._add_router_port.assert_called_once_with(self.router_ports[0])

        parser = self.app.parser
        ofproto = self.app.ofproto
        match = parser.OFPMatch(metadata=5, eth_dst="fa:16:3e:50:96:f5")
        actions = [parser.OFPActionSetField(reg7=4)]
        inst = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
            parser.OFPInstructionGotoTable(const.EGRESS_TABLE),
        ]
        self.app.mod_flow.assert_called_once_with(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_LOW,
            match=match)

    def test_delete_router(self):
        self.test_create_router()
        self.app.mod_flow.reset_mock()
        self.controller.delete_by_id(l3.LogicalRouter, 'fake_router_1')
        self.app._delete_router_port.assert_called_once_with(
                self.router_ports[0])

        ofproto = self.app.ofproto
        parser = self.app.parser
        match = parser.OFPMatch(metadata=5, eth_dst="fa:16:3e:50:96:f5")
        self.app.mod_flow.assert_called_once_with(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_LOW,
            match=match)

    def test_update_router(self):
        self.test_create_router()
        subnets2 = [l2.Subnet(dhcp_ip="10.2.0.2",
                              name="private-subnet",
                              enable_dhcp=True,
                              topic="fake_tenant1",
                              gateway_ip="10.2.0.1",
                              cidr="10.2.0.0/24",
                              id="test_subnet10_2")]
        lswitch2 = l2.LogicalSwitch(subnets=subnets2,
                                    unique_key=6,
                                    name='test_lswitch_2',
                                    is_external=False,
                                    segmentation_id=42,
                                    topic='fake_tenant1',
                                    id='test_lswitch_2',
                                    version=5)
        router_ports2 = [l3.LogicalRouterPort(network="10.2.0.1/24",
                                              lswitch=lswitch2,
                                              topic="fake_tenant1",
                                              mac="fa:16:3e:50:96:f6",
                                              unique_key=7,
                                              id="fake_router_1_port2")]
        self.controller.update(lswitch2)
        router = copy.copy(self.router)
        router.ports = router_ports2
        router.version += 1
        self.app._add_router_port.reset_mock()
        self.controller.update(router)
        self.app._add_router_port.assert_called_once_with(router_ports2[0])
        self.app._delete_router_port.assert_called_once_with(
                self.router_ports[0])
