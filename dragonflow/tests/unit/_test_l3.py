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
from dragonflow.db.models import l3
from dragonflow.tests.unit import test_app_base


class L3AppTestCaseMixin(object):

    def _add_another_router_interface(self):
        router_port1 = l3.LogicalRouterPort(network="20.0.0.1/24",
                                            lswitch="fake_switch2",
                                            topic="fake_tenant1",
                                            mac="fa:16:3e:50:96:fe",
                                            unique_key=15,
                                            id="fake_router_port2")
        self.router.add_router_port(router_port1)

    def test_n_icmp_responder_for_n_router_interface(self):
        self._add_another_router_interface()
        dst_router_port = self.router.ports[0]
        with mock.patch("dragonflow.controller.common"
                        ".icmp_responder.ICMPResponder") as icmp:
            self.app._add_new_router_port(self.router, dst_router_port)
            self.assertEqual(1, icmp.call_count)

    def test_n_route_for_n_router_interface(self):
        self._add_another_router_interface()
        dst_router_port = self.router.ports[0]
        with mock.patch.object(self.app,
                               "_add_subnet_send_to_route") as method:
            self.app._add_new_router_port(self.router, dst_router_port)
            self.assertEqual(1, method.call_count)

    def test_del_add_router(self):
        self.app.mod_flow.reset_mock()
        # delete router
        self.controller.delete(self.router)
        # 5 mod flows, l2 -> l3, arp, icmp, router interface and route.
        self.assertEqual(5, self.app.mod_flow.call_count)

        # add router
        self.app.mod_flow.reset_mock()
        self.controller.update(self.router)
        # 5 mod flows, l2 -> l3, arp, icmp, router interface and route.
        self.assertEqual(5, self.app.mod_flow.call_count)
        args, kwargs = self.app.mod_flow.call_args
        self.assertEqual(const.L3_LOOKUP_TABLE, kwargs['table_id'])

    def test_reply_ttl_invalid_message_with_rate_limit(self):
        event = mock.Mock()
        event.msg.reason = self.app.ofproto.OFPR_INVALID_TTL
        with mock.patch.object(self.app, "router_port_rarp_cache") as rarp:
            rarp.get = mock.Mock(return_value="10.0.0.1")
            with mock.patch("ryu.lib.packet.packet.Packet"):
                with mock.patch("dragonflow.controller.common."
                                "icmp_error_generator.generate") as icmp_error:
                    eui_patcher = mock.patch("netaddr.EUI")
                    eui_patcher.start()
                    self.addCleanup(eui_patcher.stop)
                    self.app.packet_in_handler(event)
                    self.app.packet_in_handler(event)
                    self.app.packet_in_handler(event)
                    self.app.packet_in_handler(event)

                    self.assertEqual(self.app.conf.router_ttl_invalid_max_rate,
                                     icmp_error.call_count)
                    icmp_error.assert_called_with(icmp.ICMP_TIME_EXCEEDED,
                                                  icmp.ICMP_TTL_EXPIRED_CODE,
                                                  mock.ANY, "10.0.0.1",
                                                  mock.ANY)

    def test_reply_icmp_unreachable_with_rate_limit(self):
        with mock.patch.object(self.app, "router_port_rarp_cache") as rarp:
            rarp.values.return_value = ["10.0.0.1"]
            event = mock.Mock()
            fake_ip_pkt = mock.Mock()
            fake_ip_pkt.dst = "10.0.0.1"
            fake_pkt = mock.Mock()
            fake_pkt.get_protocol.return_value = fake_ip_pkt
            with mock.patch("ryu.lib.packet.packet.Packet",
                            return_value=fake_pkt):
                with mock.patch("dragonflow.controller.common."
                                "icmp_error_generator.generate") as icmp_error:
                    self.app.packet_in_handler(event)
                    self.app.packet_in_handler(event)
                    self.app.packet_in_handler(event)
                    self.app.packet_in_handler(event)

                    self.assertEqual(
                        self.app.conf.router_port_unreach_max_rate,
                        icmp_error.call_count)
                    icmp_error.assert_called_with(icmp.ICMP_DEST_UNREACH,
                                                  icmp.ICMP_PORT_UNREACH_CODE,
                                                  mock.ANY, pkt=fake_pkt)

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
        router_with_route.routes = routes
        router_with_route.version += 1
        self.controller.update(router_with_route)
        # 2 routes, 2 mod_flow
        self.assertEqual(2, self.app.mod_flow.call_count)

        # delete route
        self.app.mod_flow.reset_mock()
        self.router.routes = []
        self.router.version += 2
        self.controller.update(self.router)
        self.assertEqual(2, self.app.mod_flow.call_count)

    def test_no_route_if_no_match_lport(self):
        # add route
        routes = [{"destination": "10.100.0.0/16",
                   "nexthop": "10.0.0.106"},
                  {"destination": "10.101.0.0/16",
                   "nexthop": "10.0.0.106"}]
        self.controller.update_lport(test_app_base.fake_local_port1)
        self.app.mod_flow.reset_mock()
        router_with_route = copy.deepcopy(self.router)
        router_with_route.routes = routes
        router_with_route.version += 1
        self.controller.update(router_with_route)
        self.assertFalse(self.app.mod_flow.called)
