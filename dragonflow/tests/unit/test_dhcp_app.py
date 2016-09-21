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
from oslo_config import cfg
from ryu.lib import addrconv

from dragonflow.controller.common import constants as const
from dragonflow.controller import dhcp_app
from dragonflow.tests import base as tests_base


class TestDHCPApp(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDHCPApp, self).setUp()
        self.app = dhcp_app.DHCPApp(mock.Mock())

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
