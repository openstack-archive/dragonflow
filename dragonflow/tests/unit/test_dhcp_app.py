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
import netaddr
from oslo_config import cfg
from ryu.lib import addrconv
from ryu.lib.packet import dhcp

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base

from dragonflow.db.models import l2


class Option(object):
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


class TestDHCPApp(test_app_base.DFAppTestBase):
    apps_list = "dhcp_app.DHCPApp"

    def setUp(self):
        super(TestDHCPApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]

    def test_host_route_include_metadata_route(self):
        cfg.CONF.set_override('df_add_link_local_route', True,
                              group='df_dhcp_app')
        subnet = test_app_base.fake_logic_switch1.subnets[0]
        host_route_bin = self.app._get_host_routes_list_bin(
            subnet, test_app_base.fake_local_port1)
        self.assertIn(addrconv.ipv4.text_to_bin(const.METADATA_SERVICE_IP),
                      host_route_bin)

    def test_update_dhcp_subnet_redownload_dhcp_flow(self):
        fake_lswitch = copy.copy(test_app_base.fake_logic_switch1)
        fake_lswitch.subnets[0].enable_dhcp = False
        fake_lswitch.subnets[0].dhcp_ip = None
        # Bump the version to pass the version check
        fake_lswitch.version += 1
        self.app._install_dhcp_flow_for_vm_port = mock.Mock()
        self.controller.update(fake_lswitch)
        self.controller.update(test_app_base.fake_local_port1)
        self.assertFalse(self.app._install_dhcp_flow_for_vm_port.called)

        fake_lswitch1 = copy.copy(fake_lswitch)
        fake_lswitch1.subnets[0].enable_dhcp = True
        fake_lswitch1.subnets[0].dhcp_ip = "10.0.0.2"
        # Bump the version to pass the version check
        fake_lswitch1.version += 1
        self.controller.update(fake_lswitch1)
        self.assertTrue(self.app._install_dhcp_flow_for_vm_port.called)

    def test_update_dhcp_ip_subnet_redownload_dhcp_unicast_flow(self):
        self.controller.update(test_app_base.fake_local_port1)

        fake_lswitch = copy.deepcopy(test_app_base.fake_logic_switch1)
        fake_lswitch.subnets[0].dhcp_ip = "10.0.0.100"
        # Bump the version to pass the version check
        fake_lswitch.version += 1
        self.app._install_dhcp_unicast_match_flow = mock.Mock()
        self.app._remove_dhcp_unicast_match_flow = mock.Mock()
        self.app._install_dhcp_flow_for_vm_in_subnet = mock.Mock()
        self.controller.update(fake_lswitch)
        self.assertFalse(self.app._install_dhcp_flow_for_vm_in_subnet.called)
        self.app._install_dhcp_unicast_match_flow.assert_called_once_with(
            netaddr.IPAddress('10.0.0.100'),
            test_app_base.fake_logic_switch1.unique_key)
        self.app._remove_dhcp_unicast_match_flow.assert_called_once_with(
            test_app_base.fake_logic_switch1.unique_key,
            netaddr.IPAddress('10.0.0.2'))

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

    def test_remove_local_port(self):
        fake_lport = copy.deepcopy(test_app_base.fake_local_port1)
        fake_lport.ips = ['2222:2222::2']
        self.controller.update(fake_lport)
        subnet = fake_lport.subnets[0]
        self.app.subnet_vm_port_map[subnet.id] = {fake_lport.id}
        # test case: lport has non-ipv4 IP
        self.app._remove_local_port(fake_lport)
        self.assertIn(fake_lport.id, self.app.subnet_vm_port_map[subnet.id])

        fake_lport.ips = ['10.0.0.6']
        self.app._uninstall_dhcp_flow_for_vm_port = mock.Mock()
        # test case: lport has valid ip
        self.app._remove_local_port(fake_lport)
        self.assertNotIn(fake_lport.id,
                         self.app.subnet_vm_port_map[subnet.id])
        self.app._uninstall_dhcp_flow_for_vm_port.assert_called_once()

    def test_remove_logical_switch(self):
        fake_lswitch = test_app_base.fake_logic_switch1
        network_id = fake_lswitch.unique_key
        self.app._remove_dhcp_unicast_match_flow = mock.Mock()
        self.app.remove_logical_switch(fake_lswitch)
        self.assertNotIn(network_id, self.app.switch_dhcp_ip_map)

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

    def test_extra_dhcp_opts_serilization(self):
        fake_lport = copy.deepcopy(test_app_base.fake_local_port1)
        json = fake_lport.to_json()
        loaded_lport = l2.LogicalPort.from_json(json)
        loaded_lport.validate()

    def _create_fake_empty_packet(self):
        pkt = ryu_packet.Packet()
        pkt.add_protocol(ethernet.ethernet(
            ethertype=ether.ETH_TYPE_IP))
        pkt.add_protocol(ipv4.ipv4())
        return pkt

    def test_dhcp_repsonse(self):

        req = dhcp.dhcp(op=dhcp.DHCP_DISCOVER, chaddr='aa:aa:aa:aa:aa:aa')

        fake_lport = test_app_base.make_fake_local_port(
            lswitch=test_app_base.fake_logic_switch1,
            subnets=test_app_base.fake_lswitch_default_subnets,
            ips=('1.2.3.4',)
        )

        pkt = self._create_fake_empty_packet()
        dhcp_response_pkt = self.app._create_dhcp_response(pkt,
                                                           req,
                                                           dhcp.DHCP_OFFER,
                                                           fake_lport)

        self.assertTrue(dhcp_response_pkt)

        dhcp_response = dhcp_response_pkt.get_protocol(dhcp.dhcp)
        self.assertEqual(str(dhcp_response.yiaddr), '1.2.3.4')
