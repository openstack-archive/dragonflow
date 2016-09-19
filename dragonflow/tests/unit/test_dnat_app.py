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


class TestDNATApp(test_app_base.DFAppTestBase):
    apps_list = "dnat_app.DNATApp"

    def setUp(self):
        super(TestDNATApp, self).setUp()
        self.dnat_app = self.open_flow_app.dispatcher.apps[0]
        self.dnat_app.external_ofport = 99

    def test_add_local_port(self):
        self.dnat_app.local_floatingips[
            test_app_base.fake_floatingip1.get_id()] = (
                test_app_base.fake_floatingip1)
        self.controller.logical_port_created(test_app_base.fake_local_port1)

        # Assert calls have been placed
        self.arp_responder.assert_called_once_with(
            self.datapath, None,
            test_app_base.fake_floatingip1.get_ip_address(),
            test_app_base.fake_floatingip1.get_mac_address(),
            constants.INGRESS_NAT_TABLE)
        self.dnat_app.add_flow_go_to_table.assert_has_calls(
            [mock.call(self.datapath,
                       constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                       constants.PRIORITY_DEFAULT,
                       constants.INGRESS_NAT_TABLE,
                       match=mock.ANY),
             mock.call(self.datapath,
                       constants.L3_LOOKUP_TABLE,
                       constants.PRIORITY_MEDIUM,
                       constants.EGRESS_NAT_TABLE,
                       match=mock.ANY)])
        self.dnat_app.mod_flow.assert_called_once_with(
            self.datapath, inst=mock.ANY, table_id=constants.INGRESS_NAT_TABLE,
            priority=constants.PRIORITY_MEDIUM, match=mock.ANY)
