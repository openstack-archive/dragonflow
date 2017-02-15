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

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base


class TestL3App(test_app_base.DFAppTestBase):
    apps_list = "l3_app.L3App"

    def setUp(self):
        super(TestL3App, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]
        self.mock_mod_flow = mock.Mock(name='mod_flow')
        self.app.mod_flow = self.mock_mod_flow
        self.router = test_app_base.fake_logic_router1

    def test_add_del_router(self):
        self.controller.delete_lrouter(self.router.get_id())
        self.assertEqual(4, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()
        self.controller.update_lrouter(self.router)
        self.assertEqual(3, self.mock_mod_flow.call_count)
        args, kwargs = self.mock_mod_flow.call_args
        self.assertEqual(const.L2_LOOKUP_TABLE, kwargs['table_id'])

    def test_install_l3_flow_set_metadata(self):
        dst_router_port = self.router.get_ports()[0]
        dst_port = test_app_base.fake_local_port1
        dst_metadata = dst_port.get_external_value('local_network_id')
        mock_msg = mock.Mock()
        self.app._install_l3_flow(dst_router_port, dst_port,
                                  mock_msg, mock.ANY)
        self.app.parser.OFPActionSetField.assert_any_call(
            metadata=dst_metadata)

    def test_install_l3_flow_use_buffer(self):
        dst_router_port = self.router.get_ports()[0]
        dst_port = test_app_base.fake_local_port1
        mock_msg = mock.Mock()
        mock_msg.buffer_id = mock.sentinel.buffer_id
        self.app._install_l3_flow(dst_router_port, dst_port,
                                  mock_msg, mock.ANY)
        self.app.mod_flow.assert_called_once_with(
            cookie=dst_router_port.get_unique_key(),
            inst=mock.ANY,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=mock.ANY,
            buffer_id=mock.sentinel.buffer_id,
            idle_timeout=self.app.idle_timeout,
            hard_timeout=self.app.hard_timeout)
