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

import copy
import mock

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base


class TestL2App(test_app_base.DFAppTestBase):
    apps_list = "l2_app.L2App"

    def setUp(self):
        super(TestL2App, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]

    def test_multicast_flow_for_remote_port(self):
        self.controller.logical_port_updated(test_app_base.fake_remote_port1)
        # The multicast flow will be added to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            datapath=self.datapath,
            inst=mock.ANY,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_ADD,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

        remote_port2 = copy.deepcopy(test_app_base.fake_remote_port1)
        remote_port2.inner_obj['id'] = 'fake_remote_port2'
        self.controller.logical_port_updated(remote_port2)
        # The multicast flow will be modified to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            datapath=self.datapath,
            inst=mock.ANY,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_MODIFY,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

        self.controller.logical_port_deleted('fake_remote_port2')
        # The multicast flow will be modified to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            datapath=self.datapath,
            inst=mock.ANY,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_MODIFY,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

        self.controller.logical_port_deleted(
            test_app_base.fake_remote_port1.get_id())
        # The multicast flow will be deleted to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            datapath=self.datapath,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
