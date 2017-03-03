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

import copy

import mock

from dragonflow.tests.unit import _test_l3
from dragonflow.tests.unit import test_app_base


class TestL3ProactiveApp(test_app_base.DFAppTestBase,
                         _test_l3.L3AppTestCaseMixin):
    apps_list = "l3_proactive_app.L3ProactiveApp"

    def setUp(self):
        super(TestL3ProactiveApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]
        self.router = copy.deepcopy(test_app_base.fake_logic_router1)

    def test_add_del_lport_after_router_route(self):
        # add route
        routes = [{"destination": "10.100.0.0/16",
                   "nexthop": "10.0.0.6"},
                  {"destination": "10.101.0.0/16",
                   "nexthop": "10.0.0.6"}]
        # Use another object here to differentiate the one in cache
        router_with_route = copy.deepcopy(self.router)
        router_with_route.inner_obj['routes'] = routes
        router_with_route.inner_obj['version'] += 1
        self.controller.update_lrouter(router_with_route)
        # No lport no flow for route
        self.assertFalse(self.app.mod_flow.called)

        self.controller.update_lport(test_app_base.fake_local_port1)
        # 2 routes, 2 mod_flow and 1 mod_flow for add lport proactive route
        self.assertEqual(3, self.app.mod_flow.call_count)

        self.app.mod_flow.reset_mock()
        self.controller.delete_lport('fake_port1')
        # 2 routes, 2 mod_flow and 1 mod_flow for del lport proactive route
        self.assertEqual(3, self.app.mod_flow.call_count)

    def _test_add_port(self, lport):
        with mock.patch('dragonflow.controller.l3_proactive_app.'
                        'L3ProactiveApp._add_port_process'
                        ) as fake_add_port_process:
            self.controller.update_lport(lport)
            fake_add_port_process.assert_called_once_with(
                lport.get_ip(),
                lport.get_mac(),
                lport.get_external_value('local_network_id'),
                lport.get_unique_key()
            )

    def _test_remove_port(self, lport):
        self.controller.update_lport(lport)
        with mock.patch('dragonflow.controller.l3_proactive_app.'
                        'L3ProactiveApp._remove_port_process'
                        ) as fake_remove_port_process:
            self.controller.delete_lport(lport.get_id())
            fake_remove_port_process.assert_called_once_with(
                lport.get_ip(),
                lport.get_external_value('local_network_id'),
            )

    def test_add_local_port(self):
        # add local port
        self._test_add_port(test_app_base.fake_local_port1)

    def test_remove_local_port(self):
        self._test_remove_port(test_app_base.fake_local_port1)

    def test_add_remote_port(self):
        # add remote port
        self._test_add_port(test_app_base.fake_remote_port1)

    def test_remove_remote_port(self):
        self._test_remove_port(test_app_base.fake_remote_port1)
