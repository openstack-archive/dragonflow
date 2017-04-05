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
from ryu.lib.packet import icmp

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit.controller import _test_app_base


class L3AppTestCaseMixin(object):

    def _add_another_router_interface(self):
        router_port1 = {"network": "20.0.0.1/24",
                        "lswitch": "fake_switch2",
                        "topic": "fake_tenant1",
                        "mac": "fa:16:3e:50:96:fe",
                        "unique_key": 15,
                        "lrouter": "fake_router_id",
                        "id": "fake_router_port2"}
        self.router.inner_obj['ports'].append(router_port1)

    def test_n_icmp_responder_for_n_router_interface(self):
        self._add_another_router_interface()
        dst_router_port = self.router.get_ports()[0]
        with mock.patch("dragonflow.controller.common"
                        ".icmp_responder.ICMPResponder") as icmp:
            self.app._add_new_router_port(self.router, dst_router_port)
            self.assertEqual(1, icmp.call_count)

    def test_n_route_for_n_router_interface(self):
        self._add_another_router_interface()
        dst_router_port = self.router.get_ports()[0]
        with mock.patch.object(self.app,
                               "_add_subnet_send_to_route") as method:
            self.app._add_new_router_port(self.router, dst_router_port)
            self.assertEqual(1, method.call_count)

    def test_del_add_router(self):
        _add_subnet_send_to_snat = mock.patch.object(
            self.app,
            '_add_subnet_send_to_snat'
        )
        self.addCleanup(_add_subnet_send_to_snat.stop)
        _add_subnet_send_to_snat.start()
        _del_subnet_send_to_snat = mock.patch.object(
            self.app,
            '_delete_subnet_send_to_snat'
        )
        self.addCleanup(_del_subnet_send_to_snat.stop)
        _del_subnet_send_to_snat.start()

        # delete router
        self.controller.delete_lrouter(self.router.get_id())
        # 5 mod flows, l2 -> l3, arp, icmp, router interface and route.
        self.assertEqual(5, self.app.mod_flow.call_count)
        self.app._delete_subnet_send_to_snat.assert_called_once_with(
            _test_app_base.fake_logic_switch1.get_unique_key(),
            self.router.get_ports()[0].get_mac(),
        )

        # add router
        self.app.mod_flow.reset_mock()
        self.controller.update_lrouter(self.router)
        self.assertEqual(5, self.app.mod_flow.call_count)
        args, kwargs = self.app.mod_flow.call_args
        self.assertEqual(const.L3_LOOKUP_TABLE, kwargs['table_id'])
        self.app._add_subnet_send_to_snat.assert_called_once_with(
            _test_app_base.fake_logic_switch1.get_unique_key(),
            self.router.get_ports()[0].get_mac(),
            self.router.get_ports()[0].get_unique_key()
        )

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

    def test_add_del_router_route_after_lport(self):
        self.controller.update_lport(_test_app_base.fake_local_port1)
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

    def test_no_route_if_no_match_lport(self):
        # add route
        routes = [{"destination": "10.100.0.0/16",
                   "nexthop": "10.0.0.106"},
                  {"destination": "10.101.0.0/16",
                   "nexthop": "10.0.0.106"}]
        self.controller.update_lport(_test_app_base.fake_local_port1)
        self.app.mod_flow.reset_mock()
        router_with_route = copy.deepcopy(self.router)
        router_with_route.inner_obj['routes'] = routes
        router_with_route.inner_obj['version'] += 1
        self.controller.update_lrouter(router_with_route)
        self.assertFalse(self.app.mod_flow.called)
