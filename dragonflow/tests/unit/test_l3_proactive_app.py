# Copyright (c) 2015 OpenStack Foundation.
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

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base


class TestL3ProactiveApp(test_app_base.DFAppTestBase):
    apps_list = "l3_proactive_app.L3ProactiveApp"

    def setUp(self):
        super(TestL3ProactiveApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]
        self.mock_mod_flow = mock.Mock(name='mod_flow')
        self.app.mod_flow = self.mock_mod_flow
        self.router = test_app_base.fake_logic_router1

    def test_add_del_route(self):
        # delete router
        self.controller.router_deleted(self.router.get_id())
        self.assertEqual(5, self.mock_mod_flow.call_count)

        # add router
        self.mock_mod_flow.reset_mock()
        self.controller.router_created(self.router)
        self.assertEqual(4, self.mock_mod_flow.call_count)
        args, kwargs = self.mock_mod_flow.call_args
        self.assertEqual(const.L2_LOOKUP_TABLE, kwargs['table_id'])
        self.mock_mod_flow.reset_mock()

        # add route
        route = {"destination": "10.100.0.0/16",
                 "nexthop": "10.0.0.6"}
        router_with_route = copy.deepcopy(self.router)
        router_with_route.inner_obj['routes'] = [route]
        router_with_route.inner_obj['version'] += 1
        self.controller.logical_port_created(test_app_base.fake_local_port1)
        self.controller.router_updated(router_with_route)
        self.assertEqual(2, self.mock_mod_flow.call_count)

        # delete route
        self.mock_mod_flow.reset_mock()
        self.router.inner_obj['routes'] = []
        self.router.inner_obj['version'] += 2
        self.controller.router_updated(self.router)
        self.assertEqual(1, self.mock_mod_flow.call_count)
