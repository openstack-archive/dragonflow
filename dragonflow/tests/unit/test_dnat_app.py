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

    def test_external_bridge_online(self):
        self.dnat_app.local_floatingips[
            test_app_base.fake_floatingip1.get_id()] = (
                test_app_base.fake_floatingip1)

        with mock.patch.object(self.dnat_app,
                               '_install_dnat_egress_rules') as mock_func:
            fake_ovs_port = mock.Mock()
            fake_ovs_port.get_ofport = mock.Mock(return_value=-1)
            fake_ovs_port.get_name = mock.Mock(
                return_value=self.dnat_app.external_network_bridge)
            # Device without mac will not trigger update flow
            fake_ovs_port.get_mac_in_use = mock.Mock(return_value="")
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Other device update will not trigger update flow
            fake_ovs_port.get_mac_in_use = mock.Mock(
                return_value="aa:bb:cc:dd:ee:ff")
            fake_ovs_port.get_name = mock.Mock(return_value="no-bridge")
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Device with mac will trigger update flow
            fake_ovs_port.get_name = mock.Mock(
                return_value=self.dnat_app.external_network_bridge)
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_called_once_with(test_app_base.fake_floatingip1,
                                              "aa:bb:cc:dd:ee:ff")
            mock_func.reset_mock()

            # Duplicated updated will not trigger update flow
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_not_called()
