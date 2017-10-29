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

import copy
import mock

from neutron_lib import constants as n_const
from oslo_config import cfg
from ryu.lib import addrconv
from ryu.lib.packet import dhcp
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet as ryu_packet
from ryu.ofproto import ether

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base


class Option(object):
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


class TestDHCPApp(test_app_base.DFAppTestBase):
    apps_list = ["dhcp"]

    def setUp(self):
        super(TestDHCPApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps['dhcp']

    def test_host_route_include_metadata_route(self):
        cfg.CONF.set_override('df_add_link_local_route', True,
                              group='df_dhcp_app')
        subnet = test_app_base.fake_logic_switch1.subnets[0]
        host_route_bin = self.app._get_host_routes_list_bin(
            subnet, test_app_base.fake_local_port1)
        self.assertIn(addrconv.ipv4.text_to_bin(const.METADATA_SERVICE_IP),
                      host_route_bin)

    def test__get_dhcp_message_type_opt(self):
        fake_dhcp_packet = mock.Mock()
        fake_dhcp_packet.options.option_list = (
            [Option(dhcp.DHCP_MESSAGE_TYPE_OPT, 'a'),
             Option(dhcp.DHCP_HOST_NAME_OPT, 'b')])
        a_unicode = ord('a')
        opt_value = self.app._get_dhcp_message_type_opt(fake_dhcp_packet)
        self.assertEqual(a_unicode, opt_value)
        fake_dhcp_packet.options.option_list = (
            [Option(dhcp.DHCP_END_OPT, 'a'),
             Option(dhcp.DHCP_HOST_NAME_OPT, 'b')])
        opt_value2 = self.app._get_dhcp_message_type_opt(fake_dhcp_packet)
        self.assertIsNone(opt_value2)

    def test_host_route_include_port_dhcp_opt_121(self):
        subnet = test_app_base.fake_logic_switch1.subnets[0]
        host_route_bin = self.app._get_host_routes_list_bin(
            subnet, test_app_base.fake_local_port1)
        self.assertIn(addrconv.ipv4.text_to_bin('10.0.0.1'), host_route_bin)

    def test_gateway_include_port_dhcp_opt_3(self):
        subnet = copy.copy(test_app_base.fake_logic_switch1.subnets[0])
        subnet.gateway_ip = None
        gateway_ip = self.app._get_port_gateway_address(
            subnet, test_app_base.fake_local_port1)
        self.assertEqual('10.0.0.1', str(gateway_ip))

    def test__get_port_mtu(self):
        expected_mtu = test_app_base.fake_local_port1.lswitch.mtu
        mtu = self.app._get_port_mtu(test_app_base.fake_local_port1)
        self.assertEqual(expected_mtu, mtu)
        test_app_base.fake_local_port1.lswitch.mtu = None

        def _cleanUp():
            test_app_base.fake_local_port1.lswitch.mtu = expected_mtu
        self.addCleanup(_cleanUp)
        mtu = self.app._get_port_mtu(test_app_base.fake_local_port1)
        self.assertEqual(cfg.CONF.df_dhcp_app.df_default_network_device_mtu,
                         mtu)

    def _create_dhcp_port(self):
        fake_dhcp_port = test_app_base.make_fake_local_port(
            lswitch=test_app_base.fake_logic_switch1,
            subnets=test_app_base.fake_lswitch_default_subnets,
            ips=('10.0.0.2',),
            device_owner=n_const.DEVICE_OWNER_DHCP
        )

        return fake_dhcp_port

    def _build_dhcp_test_fake_lport(self, dhcp_params=None):

        dhcp_port = self._create_dhcp_port()
        self.app._lport_created(dhcp_port)

        fake_loprt = test_app_base.make_fake_local_port(
            lswitch=test_app_base.fake_logic_switch1,
            subnets=test_app_base.fake_lswitch_default_subnets,
            ips=('10.0.0.1',),
            macs=("11:22:33:44:55:66",),
            dhcp_params=dhcp_params
        )

        return fake_loprt

    def _send_dhcp_req_to_app(self, lport, options=None):
        req = dhcp.dhcp(op=dhcp.DHCP_DISCOVER,
                        chaddr='aa:aa:aa:aa:aa:aa',
                        options=dhcp.options(options))
        pkt = self._create_fake_empty_packet()
        dhcp_response_pkt = self.app._create_dhcp_response(pkt,
                                                           req,
                                                           dhcp.DHCP_OFFER,
                                                           lport)

        return dhcp_response_pkt

    def _create_fake_empty_packet(self):
        pkt = ryu_packet.Packet()
        pkt.add_protocol(ethernet.ethernet(
            ethertype=ether.ETH_TYPE_IP))
        pkt.add_protocol(ipv4.ipv4())
        return pkt

    def test_dhcp_repsonse(self):

        fake_loprt = self._build_dhcp_test_fake_lport()
        dhcp_response_pkt = self._send_dhcp_req_to_app(fake_loprt)
        self.assertTrue(dhcp_response_pkt)
        dhcp_response = dhcp_response_pkt.get_protocol(dhcp.dhcp)
        self.assertEqual('10.0.0.1', str(dhcp_response.yiaddr))
        dhcp_eth = dhcp_response_pkt.get_protocol(ethernet.ethernet)
        self.assertEqual("11:22:33:44:55:66", str(dhcp_eth.src))

    def _create_dhcp_reponse(self, dhcp_opts, requested):

        dhcp_params = {"opts": {} if not dhcp_opts else dhcp_opts}

        fake_lport = self._build_dhcp_test_fake_lport(dhcp_params)
        requested_option_connected = ''.join([chr(x) for x in requested])

        option_list = [dhcp.option(dhcp.DHCP_PARAMETER_REQUEST_LIST_OPT,
                                   requested_option_connected,
                                   len(requested))
                       ]

        dhcp_response_pkt = self._send_dhcp_req_to_app(fake_lport,
                                                       option_list)

        dhcp_res = dhcp_response_pkt.get_protocol(dhcp.dhcp)
        self.assertTrue(dhcp_res.options)
        self.assertTrue(dhcp_res.options.option_list)

        return dhcp_res

    def test_dhcp_request_params_response_not_override_defualt(self):

        dhcp_opts = {
            1: "error"
        }

        dhcp_res = self._create_dhcp_reponse(dhcp_opts, [1])

        val = self.app._get_dhcp_option_by_tag(dhcp_res, 1)
        self.assertNotEqual(b'error', val)

    def test_dhcp_request_params_response_according_to_opt(self):

        dhcp_opts = {
            31: "a"
        }

        dhcp_res = self._create_dhcp_reponse(dhcp_opts, [31])

        val = self.app._get_dhcp_option_by_tag(dhcp_res, 31)
        self.assertEqual(b'a', val)

    def test_dhcp_esponse_not_answer_unrequested_param(self):

        dhcp_opts = {
            31: "a"
        }

        dhcp_res = self._create_dhcp_reponse(dhcp_opts, [32])

        val = self.app._get_dhcp_option_by_tag(dhcp_res, 31)
        self.assertIsNone(val)

    def test_dhcp_requested_not_answer_on_unconfigured(self):
        dhcp_res = self._create_dhcp_reponse(None, [33])
        val = self.app._get_dhcp_option_by_tag(dhcp_res, 33)
        self.assertIsNone(val)

    def test_dhcp_flow_install(self):
        self.app._install_dhcp_port_flow = mock.Mock()
        dhcp_port = self._create_dhcp_port()
        self.app._lport_created(dhcp_port)
        self.app._install_dhcp_port_flow.assert_called_once_with(
            dhcp_port.lswitch)

    def test_dhcp_port_update(self):
        dhcp_port = self._create_dhcp_port()
        self.app._lport_created(dhcp_port)

        dhcp_port2 = self._create_dhcp_port()
        dhcp_port2.ips = ('10.1.0.0',)
        subnets = copy.deepcopy(test_app_base.fake_lswitch_default_subnets)
        subnets[0].id = 'subnet2'
        dhcp_port2.subnets = subnets

        self.app._lport_updated(dhcp_port2, dhcp_port)
        self.assertEqual(
            self.app._dhcp_ip_by_subnet[dhcp_port2.subnets[0].id],
            dhcp_port2.ips[0]
        )

    def test_dhcp_port_delete(self):
        self.app_remove_dhcp_port_flow = mock.Mock()
        dhcp_port = self._create_dhcp_port()
        self.app._lport_created(dhcp_port)
        self.assertEqual(len(self.app._dhcp_ip_by_subnet), 1)
        self.app._lport_deleted(dhcp_port)
        self.assertEqual(len(self.app._dhcp_ip_by_subnet), 0)
        self.app._remove_dhcp_network_flow(dhcp_port.lswitch)
