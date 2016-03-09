# Copyright (c) 2015 OpenStack Foundation.
#
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

from neutron import context as neutron_context

from dragonflow.tests import base as tests_base

# TODO(gsagie) use this until Ryu is in the requierments.txt
try:
    from dragonflow.controller import l3_openflow_app as of_app
except Exception:
    of_app = None


def ryu_enabled(func):
    def func_wrapper(*args, **kwargs):
        if of_app is None:
            return
        return func(*args, **kwargs)
    return func_wrapper

_FAKE_TENANT_ID_1 = 'abcd123'
_SEGMENTATION_ID_A = 1024
_SEGMENTATION_ID_B = 1025

_SUBNET_A_ID = 'subneta'
_SUBNET_A_NET = '10.0.1.0'
_SUBNET_A_MASK = '24'
_SUBNET_A_CIDR = _SUBNET_A_NET + '/' + _SUBNET_A_MASK
_PORT_SUBNET_A_IP = '10.0.1.5'
_PORT_SUBNET_A_MAC = "00:00:00:00:00:01"
_PORT_SUBNET_A_ID = '1234'
_PORT_SUBNET_A_LOCAL_NUM = 1

_SUBNET_B_ID = 'subnetb'
_SUBNET_B_NET = '10.0.2.0'
_SUBNET_B_MASK = '24'
_SUBNET_B_CIDR = _SUBNET_B_NET + '/' + _SUBNET_B_MASK
_PORT_SUBNET_B_IP = '10.0.2.5'
_PORT_SUBNET_B_MAC = "00:00:00:00:00:02"
_PORT_SUBNET_B_ID = '5678'
_PORT_SUBNET_B_LOCAL_NUM = 2

_ROUTER_ID = 'routerA'

_DP_1_ID = 123


class TestOpenflowApp(tests_base.BaseTestCase):

    def setUp(self):
        super(TestOpenflowApp, self).setUp()

        if of_app is None:
            return

        self.admin_ctx = mock.patch.object(neutron_context,
                                           "get_admin_context").start()
        self.l3_app = of_app.L3ReactiveApp(None, idle_timeout=0,
                                           hard_timeout=0)
        self._mock_bootstrap_flows_creation()

    #
    # @ryu_enabled
    # def test_app_created_and_mock_enabled(self):
    #     self.assertEqual(self.admin_ctx.call_count, 1)
    #
    # @ryu_enabled
    # def test_create_simple_env_router_first(self):
    #     self.l3_app.subnet_added_binding_cast = mock.Mock()
    #     self.l3_app.bootstrap_network_classifiers = mock.Mock()
    #     self._create_env(router_first=True)
    #     self._assert_environment_creation()
    #
    # @ryu_enabled
    # def test_create_simple_env_ports_first(self):
    #     self.l3_app.subnet_added_binding_cast = mock.Mock()
    #     self.l3_app.bootstrap_network_classifiers = mock.Mock()
    #     self._create_env()
    #     self._assert_environment_creation()
    #
    # @ryu_enabled
    # def test_switch_features_handler(self):
    #     ev = mock.Mock()
    #     ev.msg.datapath = self._create_datapath_mock(_DP_1_ID)
    #     self.l3_app.switch_features_handler(ev)
    #     self.assertTrue(self.l3_app.send_port_desc_stats_request.called)
    #
    #     # Check that the normal flow was called with table '0' and
    #     # lowest priority '0'
    #     table_arg = 1
    #     priority_arg = 2
    #     self.assertEqual(
    #         self.l3_app.add_flow_normal.call_args[0][table_arg], 0)
    #     self.assertEqual(
    #         self.l3_app.add_flow_normal.call_args[0][priority_arg], 0)
    #
    #     # Assert data path was added with id
    #     self.assertIsNotNone(self.l3_app.dp_list.get(_DP_1_ID))
    #
    # @ryu_enabled
    # def test_port_desc_handler(self):
    #     ev = mock.Mock()
    #     ev.msg.datapath = self._create_datapath_mock(_DP_1_ID)
    #     self.l3_app.switch_features_handler(ev)
    #     ev.msg.body = self._create_dp_ports_mock()
    #     self.l3_app.port_desc_stats_reply_handler(ev)
    #
    #     # Assert these methods weren't called since we dont have port
    #     # segmentation id yet from neutron
    #     self.assertFalse(self.l3_app.add_flow_metadata_by_port_num.called)
    #     self.assertFalse(self.l3_app._add_vrouter_arp_responder.called)
    #     self.assertFalse(self.l3_app.add_flow_normal_local_subnet.called)
    #
    # @ryu_enabled
    # def test_new_subnet_installed_order_ports_router_dp(self):
    #     self._create_env()
    #     self._install_new_datapath()
    #     self._assert_empty_subnet_installed()
    #
    # @ryu_enabled
    # def test_new_subnet_installed_order_router_ports_dp(self):
    #     self._create_env(router_first=True)
    #     self._install_new_datapath()
    #     self._assert_empty_subnet_installed()
    #
    # @ryu_enabled
    # def test_new_subnet_installed_order_dp_router_ports(self):
    #     self._install_new_datapath()
    #     self._create_env(router_first=True)
    #     self._assert_empty_subnet_installed()
    #
    # @ryu_enabled
    # def test_new_subnet_installed_order_dp_ports_router(self):
    #     self._install_new_datapath()
    #     self._create_env()
    #     self._assert_empty_subnet_installed()
    #
    # @ryu_enabled
    # def test_new_subnet_installed_order_ports_dp_router(self):
    #     port_a = self._create_router_port_subnet_a()
    #     port_b = self._create_router_port_subnet_b()
    #     router = self._create_router()
    #     self.l3_app.sync_port(port_a)
    #     self.l3_app.sync_port(port_b)
    #     self._install_new_datapath()
    #     self.l3_app.sync_router(router)
    #     self._assert_empty_subnet_installed()
    #
    # @ryu_enabled
    # def test_new_subnet_installed_order_router_dp_ports(self):
    #     port_a = self._create_router_port_subnet_a()
    #     port_b = self._create_router_port_subnet_b()
    #     router = self._create_router()
    #     self.l3_app.sync_router(router)
    #     self._install_new_datapath()
    #     self.l3_app.sync_port(port_a)
    #     self.l3_app.sync_port(port_b)
    #     self._assert_empty_subnet_installed()
    #
    # @ryu_enabled
    # def test_new_subnet_installed_order_dp_features_env_port_desc(self):
    #     ev = mock.Mock()
    #     ev.msg.datapath = self._create_datapath_mock(_DP_1_ID)
    #     self.l3_app.switch_features_handler(ev)
    #     self._create_env()
    #     ev.msg.body = self._create_dp_ports_mock()
    #     self.l3_app.port_desc_stats_reply_handler(ev)
    #     self._assert_empty_subnet_installed()
    #
    # def _assert_empty_subnet_installed(self):
    #
    #     seg_id_arg_flow_metadata = 4
    #     self.assertEqual(self.l3_app.add_flow_metadata_by_port_num.call_count,
    #                      2)
    #
    #     seg_ids = set()
    #     for i in range(self.l3_app.add_flow_metadata_by_port_num.call_count):
    #         seg_ids.add(self.l3_app.add_flow_metadata_by_port_num.
    #                     call_args_list[i][0][seg_id_arg_flow_metadata])
    #     self.assertEqual({_SEGMENTATION_ID_A, _SEGMENTATION_ID_B}, seg_ids)
    #
    #     seg_id_arg_vrouter_arp = 1
    #     self.assertTrue(
    #         self.l3_app._add_vrouter_arp_responder.call_count >= 2)
    #
    #     seg_ids = set()
    #     for i in range(self.l3_app._add_vrouter_arp_responder.call_count):
    #         seg_ids.add(self.l3_app._add_vrouter_arp_responder.
    #                     call_args_list[i][0][seg_id_arg_vrouter_arp])
    #
    #     self.assertEqual({_SEGMENTATION_ID_A, _SEGMENTATION_ID_B}, seg_ids)
    #
    #     mac_id_arg_vrouter_arp = 2
    #     macs = set()
    #     for i in range(self.l3_app._add_vrouter_arp_responder.call_count):
    #         macs.add(self.l3_app._add_vrouter_arp_responder.
    #                  call_args_list[i][0][mac_id_arg_vrouter_arp])
    #     self.assertEqual({_PORT_SUBNET_A_MAC, _PORT_SUBNET_B_MAC}, macs)
    #
    #     interfaces_arg_vrouter_arp = 3
    #     interfaces = set()
    #     for i in range(self.l3_app._add_vrouter_arp_responder.call_count):
    #         interfaces.add(self.l3_app._add_vrouter_arp_responder.
    #                     call_args_list[i][0][interfaces_arg_vrouter_arp])
    #     self.assertTrue({_PORT_SUBNET_A_IP, _PORT_SUBNET_B_IP}, interfaces)
    #
    #     self.assertTrue(
    #         self.l3_app.add_flow_normal_local_subnet.call_count >= 2)
    #
    #     seg_id_arg_flow_normal = 5
    #     seg_ids = set()
    #     for i in range(self.l3_app.add_flow_normal_local_subnet.call_count):
    #         seg_ids.add(self.l3_app.add_flow_normal_local_subnet.
    #                     call_args_list[i][0][seg_id_arg_flow_normal])
    #     self.assertEqual({_SEGMENTATION_ID_A, _SEGMENTATION_ID_B}, seg_ids)
    #
    #     dst_net_arg_flow_normal = 3
    #     dst_net = set()
    #     for i in range(self.l3_app.add_flow_normal_local_subnet.call_count):
    #         dst_net.add(self.l3_app.add_flow_normal_local_subnet.
    #                     call_args_list[i][0][dst_net_arg_flow_normal])
    #     self.assertEqual({_SUBNET_A_NET, _SUBNET_B_NET}, dst_net)
    #
    #     dst_mask_arg_flow_normal = 4
    #     dst_mask = set()
    #     for i in range(self.l3_app.add_flow_normal_local_subnet.call_count):
    #         dst_mask.add(self.l3_app.add_flow_normal_local_subnet.
    #                     call_args_list[i][0][dst_mask_arg_flow_normal])
    #     self.assertTrue({_SUBNET_A_MASK, _SUBNET_B_MASK}, dst_mask)
    #
    #     # Validate datapath bootstrap was called correctly
    #     self.assertEqual(self.l3_app.add_flow_go_to_table_on_arp.call_count,
    #                      1)
    #     self.assertEqual(self.l3_app.add_flow_goto_normal_on_broad.call_count,
    #                      1)
    #     self.assertEqual(self.l3_app.add_flow_goto_normal_on_mcast.call_count,
    #                      1)
    #
    # def _install_new_datapath(self):
    #     ev = mock.Mock()
    #     ev.msg.datapath = self._create_datapath_mock(_DP_1_ID)
    #     self.l3_app.switch_features_handler(ev)
    #     ev.msg.body = self._create_dp_ports_mock()
    #     self.l3_app.port_desc_stats_reply_handler(ev)
    #
    # def _mock_bootstrap_flows_creation(self):
    #     self.l3_app.add_flow_go_to_table2 = mock.Mock()
    #     self.l3_app.bootstrap_network_classifiers = mock.Mock()
    #     self.l3_app.add_flow_go_to_table_on_arp = mock.Mock()
    #     self.l3_app.add_flow_goto_normal_on_broad = mock.Mock()
    #     self.l3_app.add_flow_goto_normal_on_mcast = mock.Mock()
    #     self.l3_app.add_flow_normal = mock.Mock()
    #     self.l3_app.add_flow_metadata_by_port_num = mock.Mock()
    #     self.l3_app._add_vrouter_arp_responder = mock.Mock()
    #     self.l3_app.add_flow_normal_local_subnet = mock.Mock()
    #     self.l3_app.append_port_data_to_ports = mock.Mock()
    #     self.l3_app.send_port_desc_stats_request = mock.Mock()
    #
    # def _create_dp_ports_mock(self):
    #     port1 = mock.Mock()
    #     port2 = mock.Mock()
    #     port1.name = 'qr-' + _PORT_SUBNET_A_ID
    #     port2.name = 'qr-' + _PORT_SUBNET_B_ID
    #     port1.port_no = _PORT_SUBNET_A_LOCAL_NUM
    #     port2.port_no = _PORT_SUBNET_B_LOCAL_NUM
    #     return [port1, port2]
    #
    # def _create_datapath_mock(self, id):
    #     dp = mock.Mock()
    #     dp.id = id
    #     dp.ofproto_parser = mock.Mock()
    #     dp.ofproto = mock.Mock()
    #     return dp
    #
    # def _assert_environment_creation(self):
    #     self.assertEqual(len(self.l3_app._tenants), 1)
    #     tenant = self.l3_app.get_tenant_by_id(_FAKE_TENANT_ID_1)
    #     self.assertEqual(len(tenant.mac_to_port_data), 2)
    #     self.assertTrue(
    #         self.l3_app.subnet_added_binding_cast.call_count >= 2)
    #     self.assertTrue(
    #         self.l3_app.bootstrap_network_classifiers.call_count >= 2)
    #     subnets = tenant.subnets
    #     for id, subnet in subnets.items():
    #         self.assertIsNotNone(subnet.segmentation_id)
    #         self.assertNotEqual(subnet.segmentation_id, 0)
    #
    # def _create_env(self, router_first=False):
    #     port_a = self._create_router_port_subnet_a()
    #     port_b = self._create_router_port_subnet_b()
    #     router = self._create_router()
    #     if router_first:
    #         self.l3_app.sync_router(router)
    #     self.l3_app.sync_port(port_a)
    #     self.l3_app.sync_port(port_b)
    #     if not router_first:
    #         self.l3_app.sync_router(router)
    #
    # def _create_router(self):
    #     router_info = {}
    #     router_info['id'] = _ROUTER_ID
    #     router_info['tenant_id'] = _FAKE_TENANT_ID_1
    #     port_a = self._create_router_port_subnet_a()
    #     port_b = self._create_router_port_subnet_b()
    #     router_info['_interfaces'] = [port_a, port_b]
    #     return router_info
    #
    # def _create_router_port_subnet_a(self):
    #     port = {}
    #     port['id'] = _PORT_SUBNET_A_ID
    #     port['tenant_id'] = _FAKE_TENANT_ID_1
    #     port['segmentation_id'] = _SEGMENTATION_ID_A
    #     port['mac_address'] = _PORT_SUBNET_A_MAC
    #     port['device_owner'] = constants.DEVICE_OWNER_ROUTER_INTF
    #     subnet = dict(id=_SUBNET_A_ID, cidr=_SUBNET_A_CIDR)
    #     ip_addr = dict(subnet_id=_SUBNET_A_ID, ip_address=_PORT_SUBNET_A_IP)
    #     port['fixed_ips'] = [ip_addr]
    #     port['subnets'] = [subnet]
    #     return port
    #
    # def _create_router_port_subnet_b(self):
    #     port = {}
    #     port['id'] = _PORT_SUBNET_B_ID
    #     port['tenant_id'] = _FAKE_TENANT_ID_1
    #     port['segmentation_id'] = _SEGMENTATION_ID_B
    #     port['mac_address'] = _PORT_SUBNET_B_MAC
    #     port['device_owner'] = constants.DEVICE_OWNER_ROUTER_INTF
    #     subnet = dict(id=_SUBNET_B_ID, cidr=_SUBNET_B_CIDR)
    #     ip_addr = dict(subnet_id=_SUBNET_B_ID, ip_address=_PORT_SUBNET_B_IP)
    #     port['fixed_ips'] = [ip_addr]
    #     port['subnets'] = [subnet]
    #     return port
