# Copyright (c) 2016 OpenStack Foundation.
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


class TestL2App(test_app_base.DFAppTestBase):
    apps_list = ["l2"]

    def setUp(self):
        super(TestL2App, self).setUp()
        fake_local_switch1 = l2.LogicalSwitch(
                subnets=test_app_base.fake_lswitch_default_subnets,
                network_type='local',
                id='fake_local_switch1',
                segmentation_id=41,
                mtu=1500,
                topic='fake_tenant1',
                unique_key=1,
                is_external=False,
                name='private')
        self.controller.update(fake_local_switch1)
        self.app = self.open_flow_app.dispatcher.apps['l2']

    def test_multicast_local_port(self):
        fake_local_port1 = test_app_base.make_fake_local_port(
                macs=['00:0b:0c:0d:0e:0f'],
                ips=['10.0.0.11'],
                lswitch='fake_local_switch1')
        self.controller.update(fake_local_port1)
        self.app.mod_flow.assert_any_call(
            inst=mock.ANY,
            command=self.app.ofproto.OFPFC_ADD,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

        fake_local_port2 = test_app_base.make_fake_local_port(
                lswitch='fake_local_switch1',
                macs=['1a:0b:0c:0d:0e:0f'],
                ips=['10.0.0.12'])
        self.controller.update(fake_local_port2)
        self.app.mod_flow.assert_any_call(
            inst=mock.ANY,
            command=self.app.ofproto.OFPFC_MODIFY,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()
