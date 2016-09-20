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

from dragonflow.tests.unit import test_app_base


class TestMetadataServiceApp(test_app_base.DFAppTestBase):
    apps_list = "metadata_service_app.MetadataServiceApp"

    def setUp(self):
        super(TestMetadataServiceApp, self).setUp()
        self.meta_app = self.open_flow_app.dispatcher.apps[0]

    def test_metadata_interface_online(self):
        with mock.patch.object(self.meta_app,
                               '_add_tap_metadata_port') as mock_func:
            fake_ovs_port = mock.Mock()
            fake_ovs_port.get_ofport = mock.Mock(return_value=1)
            fake_ovs_port.get_name = mock.Mock(
                return_value=self.meta_app._interface)
            # Device without mac will not trigger update flow
            fake_ovs_port.get_mac_in_use = mock.Mock(return_value="")
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Other device update will not trigger update flow
            fake_ovs_port.get_mac_in_use = mock.Mock(
                return_value="aa:bb:cc:dd:ee:ff")
            fake_ovs_port.get_name = mock.Mock(return_value="no-interface")
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Device with mac will trigger update flow
            fake_ovs_port.get_name = mock.Mock(
                return_value=self.meta_app._interface)
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_called_once_with(1,
                                              "aa:bb:cc:dd:ee:ff")
            mock_func.reset_mock()

            # Duplicated updated will not trigger update flow
            self.controller.ovs_port_updated(fake_ovs_port)
            mock_func.assert_not_called()
