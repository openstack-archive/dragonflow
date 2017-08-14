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
from dragonflow.tests.unit import _test_l3
from dragonflow.tests.unit import test_app_base


class TestL3App(test_app_base.DFAppTestBase,
                _test_l3.L3AppTestCaseMixin):
    apps_list = ["l3_reactive"]

    def setUp(self):
        super(TestL3App, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['l3_reactive']
        self.app.mod_flow = mock.Mock()
        self.router = copy.deepcopy(test_app_base.fake_logic_router1)

    def test_install_l3_flow_set_metadata(self):
        dst_router_port = self.router.ports[0]
        dst_port = test_app_base.fake_local_port1
        dst_metadata = dst_port.lswitch.unique_key
        mock_msg = mock.Mock()
        self.app._install_l3_flow(dst_router_port, dst_port,
                                  mock_msg, mock.ANY)
        self.app.parser.OFPActionSetField.assert_any_call(
            metadata=dst_metadata)

    def test_install_l3_flow_use_buffer(self):
        dst_router_port = self.router.ports[0]
        dst_port = test_app_base.fake_local_port1
        mock_msg = mock.Mock()
        mock_msg.buffer_id = mock.sentinel.buffer_id
        self.app._install_l3_flow(dst_router_port, dst_port,
                                  mock_msg, mock.ANY)
        self.app.mod_flow.assert_called_once_with(
            cookie=dst_router_port.unique_key,
            inst=mock.ANY,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=mock.ANY,
            buffer_id=mock.sentinel.buffer_id,
            idle_timeout=self.app.idle_timeout,
            hard_timeout=self.app.hard_timeout)

    def test_add_del_lport_after_router_route(self):
        # add route
        routes = [{"destination": "10.100.0.0/16",
                   "nexthop": "10.0.0.6"},
                  {"destination": "10.101.0.0/16",
                   "nexthop": "10.0.0.6"}]
        # Use another object here to differentiate the one in cache
        router_with_route = copy.deepcopy(self.router)
        router_with_route.routes = routes
        router_with_route.version += 1
        self.controller.update(router_with_route)
        # No lport no flow for route
        self.assertFalse(self.app.mod_flow.called)

        self.controller.update(test_app_base.fake_local_port1)
        # 2 routes, 2 mod_flow
        self.assertEqual(2, self.app.mod_flow.call_count)

        self.app.mod_flow.reset_mock()
        self.controller.delete(test_app_base.fake_local_port1)
        # 2 routes, 2 mod_flow
        self.assertEqual(2, self.app.mod_flow.call_count)
