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

from oslo_config import cfg
from ryu.lib import addrconv
from ryu.lib.packet import dhcp

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base


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
        subnet = test_app_base.fake_logic_switch1.get_subnets()[0]
        host_route_bin = self.app._get_host_routes_list_bin(
            subnet, test_app_base.fake_local_port1)
        self.assertIn(addrconv.ipv4.text_to_bin(const.METADATA_SERVICE_IP),
                      host_route_bin)

    def test_update_dhcp_subnet_redownload_dhcp_flow(self):
        fake_lswitch = copy.deepcopy(test_app_base.fake_logic_switch1)
        fake_lswitch.inner_obj['subnets'][0]['enable_dhcp'] = False
        fake_lswitch.inner_obj['subnets'][0]['dhcp_ip'] = None
        # Bump the version to pass the version check
        fake_lswitch.inner_obj['version'] += 1
        self.app._install_dhcp_flow_for_vm_port = mock.Mock()
        self.controller.update_lswitch(fake_lswitch)
        self.controller.update_lport(test_app_base.fake_local_port1)
        self.assertFalse(self.app._install_dhcp_flow_for_vm_port.called)

        fake_lswitch1 = copy.deepcopy(fake_lswitch)
        fake_lswitch1.inner_obj['subnets'][0]['enable_dhcp'] = True
        fake_lswitch1.inner_obj['subnets'][0]['dhcp_ip'] = "10.0.0.2"
        # Bump the version to pass the version check
        fake_lswitch1.inner_obj['version'] += 1
        self.controller.update_lswitch(fake_lswitch1)
        self.assertTrue(self.app._install_dhcp_flow_for_vm_port.called)

    def test_update_dhcp_ip_subnet_redownload_dhcp_unicast_flow(self):
        self.controller.update_lport(test_app_base.fake_local_port1)

        fake_lswitch = copy.deepcopy(test_app_base.fake_logic_switch1)
        fake_lswitch.inner_obj['subnets'][0]['dhcp_ip'] = "10.0.0.100"
        # Bump the version to pass the version check
        fake_lswitch.inner_obj['version'] += 1
        self.app._install_dhcp_unicast_match_flow = mock.Mock()
        self.app._remove_dhcp_unicast_match_flow = mock.Mock()
        self.app._install_dhcp_flow_for_vm_in_subnet = mock.Mock()
        self.controller.update_lswitch(fake_lswitch)
        self.assertFalse(self.app._install_dhcp_flow_for_vm_in_subnet.called)
        self.app._install_dhcp_unicast_match_flow.assert_called_once_with(
            '10.0.0.100', test_app_base.fake_logic_switch1.get_unique_key())
        self.app._remove_dhcp_unicast_match_flow.assert_called_once_with(
            test_app_base.fake_logic_switch1.get_unique_key(), '10.0.0.2')

    def test__get_lswitch_by_port(self):
        lport = test_app_base.fake_local_port1
        l_switch_id = lport.get_lswitch_id()
        fake_lswitch = test_app_base.fake_logic_switch1
        self.app.db_store.set_lswitch(l_switch_id, fake_lswitch)
        lswitch = self.app._get_lswitch_by_port(lport)
        self.assertEqual(fake_lswitch, lswitch)

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

    def test__get_subnet_by_port(self):
        fake_lport = copy.deepcopy(test_app_base.fake_local_port1)
        fake_lport_subnet = test_app_base.fake_logic_switch1.get_subnets()[0]
        subnet = self.app._get_subnet_by_port(fake_lport)
        self.assertEqual(fake_lport_subnet, subnet)

        fake_lport.inner_obj['subnets'] = ['ThisSubnetDoesNotExist']
        self.controller.update_lport(fake_lport)
        subnet = self.app._get_subnet_by_port(fake_lport)
        self.assertIsNone(subnet)

    def test_remove_local_port(self):
        fake_lport = copy.deepcopy(test_app_base.fake_local_port1)
        fake_lport.inner_obj['ips'] = ['ThisIsNotAValidIP']
        self.controller.update_lport(fake_lport)
        subnet = fake_lport.get_subnets()[0]
        self.app.subnet_vm_port_map[subnet] = set([fake_lport.get_id()])
        # test case: lport has an invalid IP
        self.app.remove_local_port(fake_lport)
        self.assertIn(fake_lport.get_id(), self.app.subnet_vm_port_map[subnet])

        fake_lport.inner_obj['ips'] = ['10.0.0.6']
        tunnel_key = fake_lport.get_unique_key()
        self.app.ofport_to_dhcp_app_port_data.update({tunnel_key: None})
        self.app._uninstall_dhcp_flow_for_vm_port = mock.Mock()
        # test case: lport has valid ip
        self.app.remove_local_port(fake_lport)
        self.assertNotIn(fake_lport.get_id(),
            self.app.subnet_vm_port_map[subnet])
        self.app._uninstall_dhcp_flow_for_vm_port.assert_called_once()

    def test_remove_logical_switch(self):
        fake_lswitch = test_app_base.fake_logic_switch1
        network_id = fake_lswitch.get_unique_key()
        self.app._remove_dhcp_unicast_match_flow = mock.Mock()
        self.app.remove_logical_switch(fake_lswitch)
        self.assertNotIn(network_id, self.app.switch_dhcp_ip_map)

    def test_host_route_include_port_dhcp_opt_121(self):
        subnet = test_app_base.fake_logic_switch1.get_subnets()[0]
        host_route_bin = self.app._get_host_routes_list_bin(
            subnet, test_app_base.fake_local_port1)
        self.assertIn(addrconv.ipv4.text_to_bin('10.0.0.1'), host_route_bin)

    def test_gateway_include_port_dhcp_opt_3(self):
        subnet = copy.copy(test_app_base.fake_logic_switch1.get_subnets()[0])
        subnet.inner_obj['gateway_ip'] = ''
        gateway_ip = self.app._get_port_gateway_address(
            subnet, test_app_base.fake_local_port1)
        self.assertEqual('10.0.0.1', str(gateway_ip))
