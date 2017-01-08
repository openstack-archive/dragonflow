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

from dragonflow.controller.common import constants
from dragonflow.tests.unit import test_app_base


class TestSNATApp(test_app_base.DFAppTestBase):
    apps_list = "snat_app.SNATApp"

    def setUp(self):
        super(TestSNATApp, self).setUp()
        self.SNAT_app = self.open_flow_app.dispatcher.apps[0]
        self.SNAT_app.external_ofport = 99

    def test_add_first_local_port(self):
        self.controller.update_lport(test_app_base.fake_local_port1)

        self.SNAT_app.mod_flow.assert_has_calls(
            [mock.call(self.datapath,
                   cookie=constants.NAT_TRACKING_ZONE,
                   inst=mock.ANY,
                   table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                   priority=constants.PRIORITY_DEFAULT,
                   match=mock.ANY)])
        self.SNAT_app.mod_flow.assert_has_calls(
            [mock.call(self.datapath,
                   cookie=0x0,
                   inst=mock.ANY,
                   table_id=constants.L3_LOOKUP_TABLE,
                   priority=constants.PRIORITY_LOW,
                   match=mock.ANY)])

    def test_remove_last_local_port(self):
        # mockup last VM port is being removed
        self.SNAT_app.count = 1

        self.controller.open_flow_app.notify_remove_local_port(
            test_app_base.fake_local_port1)

        self.SNAT_app.mod_flow.assert_has_calls(
            [mock.call(self.datapath,
                   cookie=constants.NAT_TRACKING_ZONE,
                   command=mock.ANY,
                   table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                   priority=constants.PRIORITY_DEFAULT,
                   match=mock.ANY)])
        self.SNAT_app.mod_flow.assert_has_calls(
            [mock.call(self.datapath,
                   cookie=0x0,
                   command=mock.ANY,
                   table_id=constants.L3_LOOKUP_TABLE,
                   priority=constants.PRIORITY_LOW,
                   match=mock.ANY)])
