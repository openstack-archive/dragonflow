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
from oslo_config import cfg

from dragonflow.controller.common import constants
from dragonflow.tests.unit import test_app_base


class TestChassisSNATApp(test_app_base.DFAppTestBase):
    apps_list = ["chassis_snat"]
    external_host_ip = '172.24.4.100'

    def setUp(self):
        cfg.CONF.set_override('external_host_ip',
                              self.external_host_ip,
                              group='df')
        super(TestChassisSNATApp, self).setUp()
        self.SNAT_app = self.open_flow_app.dispatcher.apps['chassis_snat']
        self.SNAT_app.external_ofport = 99

    def test_switch_features_handler(self):
        ev = mock.Mock()
        ev.msg.datapath.ofproto.OFP_VERSION = 0x04
        self.controller.open_flow_app.switch_features_handler(ev)

        self.SNAT_app.add_flow_go_to_table.assert_has_calls(
            [mock.call(
                       constants.L3_LOOKUP_TABLE,
                       constants.PRIORITY_MEDIUM_LOW,
                       constants.EGRESS_NAT_TABLE,
                       match=mock.ANY)])

        self.SNAT_app.mod_flow.assert_has_calls(
             [mock.call(
                   inst=mock.ANY,
                   table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                   priority=constants.PRIORITY_DEFAULT,
                   match=mock.ANY),
              mock.call(
                   inst=mock.ANY,
                   table_id=constants.INGRESS_NAT_TABLE,
                   priority=constants.PRIORITY_LOW,
                   match=mock.ANY),
              mock.call(
                   inst=mock.ANY,
                   table_id=constants.EGRESS_NAT_TABLE,
                   priority=constants.PRIORITY_LOW,
                   match=mock.ANY),
              mock.call(
                   actions=mock.ANY,
                   table_id=constants.EGRESS_SNAT_TABLE,
                   priority=constants.PRIORITY_LOW,
                   match=mock.ANY)])

    def test_add_local_port(self):
        self.controller.update(test_app_base.fake_local_port1)

        self.SNAT_app.mod_flow.assert_has_calls(
            [mock.call(
                   inst=mock.ANY,
                   table_id=constants.INGRESS_SNAT_TABLE,
                   priority=constants.PRIORITY_LOW,
                   match=mock.ANY)])

    def test_remove_local_port(self):
        self.controller.update(test_app_base.fake_local_port1)
        self.SNAT_app.mod_flow.reset_mock()
        self.controller.delete(test_app_base.fake_local_port1)

        self.SNAT_app.mod_flow.assert_has_calls(
            [mock.call(
                   command=mock.ANY,
                   table_id=constants.INGRESS_SNAT_TABLE,
                   priority=constants.PRIORITY_LOW,
                   match=mock.ANY)])
