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
from oslo_config import cfg
from ryu.lib import addrconv

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base


class TestDHCPApp(test_app_base.DFAppTestBase):
    apps_list = "dhcp_app.DHCPApp"

    def setUp(self):
        super(TestDHCPApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]

    def test_host_route_include_metadata_route(self):
        cfg.CONF.set_override('df_add_link_local_route', True,
                              group='df_dhcp_app')
        mock_subnet = mock.MagicMock()
        mock_subnet.get_host_routes.return_value = []
        lport = mock.MagicMock()
        lport.get_ip.return_value = "10.0.0.3"
        host_route_bin = self.app._get_host_routes_list_bin(
            mock_subnet, lport)
        self.assertIn(addrconv.ipv4.text_to_bin(const.METADATA_SERVICE_IP),
                      host_route_bin)

    def test_update_dhcp_subnet_redownload_dhcp_flow(self):
        fake_lswitch = copy.deepcopy(test_app_base.fake_logic_switch1)
        fake_lswitch.inner_obj['subnets'][0]['enable_dhcp'] = False
        fake_lswitch.inner_obj['subnets'][0]['dhcp_ip'] = None
        # Bump the version to pass the version check
        fake_lswitch.inner_obj['version'] += 1
        self.app._install_dhcp_flow_for_vm_port = mock.Mock()
        self.controller.logical_switch_updated(fake_lswitch)
        self.controller.logical_port_updated(test_app_base.fake_local_port1)
        self.assertFalse(self.app._install_dhcp_flow_for_vm_port.called)

        fake_lswitch1 = copy.deepcopy(fake_lswitch)
        fake_lswitch1.inner_obj['subnets'][0]['enable_dhcp'] = True
        fake_lswitch1.inner_obj['subnets'][0]['dhcp_ip'] = "10.0.0.2"
        # Bump the version to pass the version check
        fake_lswitch1.inner_obj['version'] += 1
        self.controller.logical_switch_updated(fake_lswitch1)
        self.assertTrue(self.app._install_dhcp_flow_for_vm_port.called)

    def test_update_dhcp_ip_subnet_redownload_dhcp_unicast_flow(self):
        self.controller.logical_port_updated(test_app_base.fake_local_port1)

        fake_lswitch = copy.deepcopy(test_app_base.fake_logic_switch1)
        fake_lswitch.inner_obj['subnets'][0]['dhcp_ip'] = "10.0.0.100"
        # Bump the version to pass the version check
        fake_lswitch.inner_obj['version'] += 1
        self.app._install_dhcp_unicast_match_flow = mock.Mock()
        self.app._remove_dhcp_unicast_match_flow = mock.Mock()
        self.app._install_dhcp_flow_for_vm_in_subnet = mock.Mock()
        self.controller.logical_switch_updated(fake_lswitch)
        self.assertFalse(self.app._install_dhcp_flow_for_vm_in_subnet.called)
        self.app._install_dhcp_unicast_match_flow.assert_called_once_with(
            '10.0.0.100', test_app_base.fake_logic_switch1.get_unique_key())
        self.app._remove_dhcp_unicast_match_flow.assert_called_once_with(
            test_app_base.fake_logic_switch1.get_unique_key(), '10.0.0.2')
