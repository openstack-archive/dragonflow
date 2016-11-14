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
        subnet = test_app_base.fake_logic_switch1.get_subnets()[0]
        host_route_bin = self.app._get_host_routes_list_bin(
            subnet, test_app_base.fake_local_port1)
        self.assertIn(addrconv.ipv4.text_to_bin(const.METADATA_SERVICE_IP),
                      host_route_bin)

    def test_host_route_include_port_dhcp_opt_121(self):
        subnet = test_app_base.fake_logic_switch1.get_subnets()[0]
        host_route_bin = self.app._get_host_routes_list_bin(
            subnet, test_app_base.fake_local_port1)
        self.assertIn(addrconv.ipv4.text_to_bin('10.0.0.1'), host_route_bin)

    def test_gateway_include_port_dhcp_opt_3(self):
        subnet = copy.copy(test_app_base.fake_logic_switch1.get_subnets()[0])
        subnet.inner_obj['gateway_ip'] = ''
        gateway_ip = self.app._get_port_gateway_address(
            subnet, test_app_base.fake_local_port1)
        self.assertEqual('10.0.0.1', str(gateway_ip))
