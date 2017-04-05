# Copyright (c) 2017 OpenStack Foundation.
# All Rights Reserved.
#
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
import mock

from dragonflow.controller.common import constants as const
from dragonflow.db.models import l2
from dragonflow.tests.unit import test_app_base

make_fake_local_port = test_app_base.make_fake_local_port


class TestClassifierApp(test_app_base.DFAppTestBase):
    apps_list = "classifier_app.ClassifierApp"

    def setUp(self):
        super(TestClassifierApp, self).setUp()
        fake_vlan_switch1 = l2.LogicalSwitch(
                subnets=test_app_base.fake_lswitch_default_subnets,
                network_type='vlan',
                id='fake_vlan_switch1', mtu=1500,
                is_external=False, segmentation_id=41,
                topic='fake_tenant1', unique_key=2,
                name='private')
        self.controller.update(fake_vlan_switch1)
        self.app = self.open_flow_app.dispatcher.apps[0]

    def test_classifier_for_vlan_port(self):
        fake_local_vlan_port = make_fake_local_port(
            network_type='vlan',
            lswitch='fake_vlan_switch1')
        port_key = fake_local_vlan_port.get_unique_key()
        match = self.app.parser.OFPMatch(reg7=port_key)
        self.controller.update_lport(fake_local_vlan_port)
        self.app.mod_flow.assert_called_with(
            inst=mock.ANY,
            table_id=const.INGRESS_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self.app.mod_flow.reset_mock()
        ofport = fake_local_vlan_port.get_external_value('ofport')
        match = self.app.parser.OFPMatch(in_port=ofport)
        self.controller.delete_lport(fake_local_vlan_port.get_id())
        self.app.mod_flow.assert_called_with(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.datapath.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self.app.mod_flow.reset_mock()
