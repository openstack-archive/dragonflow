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

from dragonflow.db.models import host_route
from dragonflow.tests.unit import _test_l3
from dragonflow.tests.unit import test_app_base


class TestL3ProactiveApp(test_app_base.DFAppTestBase,
                         _test_l3.L3AppTestCaseMixin):
    apps_list = ["l3_proactive"]

    def setUp(self):
        super(TestL3ProactiveApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['l3_proactive']
        self.app.mod_flow = mock.Mock()
        self.router = copy.deepcopy(test_app_base.fake_logic_router1)

    def test_add_del_lport_after_router_route(self):
        # add route
        routes = [host_route.HostRoute(destination="10.100.0.0/16",
                                       nexthop="10.0.0.6"),
                  host_route.HostRoute(destination="10.101.0.0/16",
                                       nexthop="10.0.0.6")]
        # Use another object here to differentiate the one in cache
        router_with_route = copy.deepcopy(self.router)
        router_with_route.routes = routes
        router_with_route.version += 1
        self.controller.update(router_with_route)
        # No lport no flow for route
        self.assertFalse(self.app.mod_flow.called)

        self.controller.update(test_app_base.fake_local_port1)
        # 2 routes, 2 mod_flow and 1 mod_flow for add lport proactive route
        self.assertEqual(4, self.app.mod_flow.call_count)

        self.app.mod_flow.reset_mock()
        self.controller.delete(test_app_base.fake_local_port1)
        # 2 routes, 2 mod_flow and 1 mod_flow for del lport proactive route
        self.assertEqual(4, self.app.mod_flow.call_count)

    def _add_test_call(self, mockpatch, *args, **kwargs):
        mockpatch.assert_any_call(*args, **kwargs)
        return mock.call(*args, **kwargs)

    def _test_add_port(self, lport):
        with mock.patch('dragonflow.controller.apps.l3_proactive.'
                        'L3ProactiveApp._add_forward_to_port_flow'
                        ) as fake_add_forward_to_port_flow:
            self.controller.update(lport)
            calls = []
            for ip in lport.ips:
                call = self._add_test_call(
                    fake_add_forward_to_port_flow,
                    ip,
                    lport.mac,
                    lport.lswitch.unique_key,
                    lport.unique_key,
                )
                calls.append(call)
            fake_add_forward_to_port_flow.assert_has_calls(calls)

    def _test_remove_port(self, lport):
        self.controller.update(lport)
        with mock.patch('dragonflow.controller.apps.l3_proactive.'
                        'L3ProactiveApp._remove_forward_to_port_flow'
                        ) as fake_remove_forward_to_port_flow:
            self.controller.delete(lport)
            calls = []
            for ip in lport.ips:
                call = self._add_test_call(
                    fake_remove_forward_to_port_flow,
                    ip,
                    lport.lswitch.unique_key,
                )
                calls.append(call)
            fake_remove_forward_to_port_flow.assert_has_calls(calls)

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
