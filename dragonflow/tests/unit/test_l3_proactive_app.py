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

from dragonflow.tests.unit import _test_l3
from dragonflow.tests.unit import test_app_base


class TestL3ProactiveApp(test_app_base.DFAppTestBase,
                         _test_l3.L3AppTestCaseMixin):
    apps_list = "l3_proactive_app.L3ProactiveApp"

    def setUp(self):
        super(TestL3ProactiveApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]
        self.router = copy.deepcopy(test_app_base.fake_logic_router1)

    def test_add_del_router_route_after_lport(self):
        self.controller.update_lport(test_app_base.fake_local_port1)
        self.app.mod_flow.reset_mock()

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
        # 2 routes, 2 mod_flow
        self.assertEqual(2, self.app.mod_flow.call_count)

        # delete route
        self.app.mod_flow.reset_mock()
        self.router.inner_obj['routes'] = []
        self.router.inner_obj['version'] += 2
        self.controller.update_lrouter(self.router)
        self.assertEqual(2, self.app.mod_flow.call_count)

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

    def test_no_route_if_no_match_lport(self):
        # add route
        routes = [{"destination": "10.100.0.0/16",
                   "nexthop": "10.0.0.106"},
                  {"destination": "10.101.0.0/16",
                   "nexthop": "10.0.0.106"}]
        self.controller.update_lport(test_app_base.fake_local_port1)
        self.app.mod_flow.reset_mock()
        router_with_route = copy.deepcopy(self.router)
        router_with_route.inner_obj['routes'] = routes
        router_with_route.inner_obj['version'] += 1
        self.controller.update_lrouter(router_with_route)
        self.assertFalse(self.app.mod_flow.called)
