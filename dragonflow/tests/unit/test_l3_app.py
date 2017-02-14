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
from ryu.lib.packet import icmp

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
        self.assertEqual(5, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()
        self.controller.update_lrouter(self.router)
        # Since there is only one router interface in the fake router
        # and the router interface is not concrete. Adding router will
        # call mod_flow 3 times less than deleting router.
        self.assertEqual(2, self.mock_mod_flow.call_count)
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

    def test_reply_ttl_invalid_message_with_rate_limit(self):
        event = mock.Mock()
        event.msg.reason = self.app.ofproto.OFPR_INVALID_TTL
        self.app.router_port_rarp_cache = mock.Mock()
        self.app.router_port_rarp_cache.get = mock.Mock(
            return_value="10.0.0.1")
        with mock.patch("ryu.lib.packet.packet.Packet"):
            with mock.patch("dragonflow.controller.common"
                            ".icmp_error_generator.generate") as icmp_error:
                self.app.packet_in_handler(event)
                self.app.packet_in_handler(event)
                self.app.packet_in_handler(event)
                self.app.packet_in_handler(event)

                self.assertEqual(self.app.conf.router_ttl_invalid_max_rate,
                                 icmp_error.call_count)
                icmp_error.assert_called_with(icmp.ICMP_TIME_EXCEEDED,
                                              icmp.ICMP_TTL_EXPIRED_CODE,
                                              mock.ANY, "10.0.0.1", mock.ANY)

    def test_reply_icmp_unreachable_with_rate_limit(self):
        self.app.router_port_rarp_cache = mock.Mock()
        self.app.router_port_rarp_cache.values.return_value = ["10.0.0.1"]
        event = mock.Mock()
        fake_ip_pkt = mock.Mock()
        fake_ip_pkt.dst = "10.0.0.1"
        fake_pkt = mock.Mock()
        fake_pkt.get_protocol.return_value = fake_ip_pkt
        with mock.patch("ryu.lib.packet.packet.Packet", return_value=fake_pkt):
            with mock.patch("dragonflow.controller.common"
                            ".icmp_error_generator.generate") as icmp_error:
                self.app.packet_in_handler(event)
                self.app.packet_in_handler(event)
                self.app.packet_in_handler(event)
                self.app.packet_in_handler(event)

                self.assertEqual(self.app.conf.router_port_unreach_max_rate,
                                 icmp_error.call_count)
                icmp_error.assert_called_with(icmp.ICMP_DEST_UNREACH,
                                              icmp.ICMP_PORT_UNREACH_CODE,
                                              mock.ANY, pkt=fake_pkt)
