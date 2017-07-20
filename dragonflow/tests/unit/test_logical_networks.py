# Copyright (c) 2017 OpenStack Foundation.
# All Rights Reserved.
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

from dragonflow.controller.common import logical_networks
from dragonflow.tests import base as tests_base
from dragonflow.tests.unit import test_app_base


class TestLogicalNetworks(tests_base.BaseTestCase):
    def setUp(self):
        super(TestLogicalNetworks, self).setUp()
        self.logical_networks = logical_networks.LogicalNetworks()

    def test_add_remove_local_port(self):
        fake_local_vlan_port1 = test_app_base.make_fake_local_port(
                name='fake_local_vlan_port1',
                unique_key=3,
                lswitch='fake_vlan_switch1')
        self.logical_networks.add_local_port(
                port_id=fake_local_vlan_port1.id,
                network_id=1,
                network_type='vlan')
        net_1_vlan_ports = self.logical_networks.get_local_port_count(
                network_id=1,
                network_type='vlan')
        self.assertEqual(1, net_1_vlan_ports)
        fake_local_vlan_port2 = test_app_base.make_fake_local_port(
                name='fake_local_vlan_port2',
                unique_key=4,
                lswitch='fake_vlan_switch1')
        self.logical_networks.add_local_port(
                port_id=fake_local_vlan_port2.id,
                network_id=1,
                network_type='vlan')
        net_1_vlan_ports = self.logical_networks.get_local_port_count(
                network_id=1,
                network_type='vlan')
        self.assertEqual(2, net_1_vlan_ports)
        net_2_gre_ports = self.logical_networks.get_local_port_count(
                network_id=2,
                network_type='gre')
        self.assertEqual(0, net_2_gre_ports)
        fake_local_gre_port1 = test_app_base.make_fake_local_port(
                lswitch='fake_gre_switch1',
                name='fake_local_gre_port1',
                unique_key=5)
        self.logical_networks.add_local_port(
                port_id=fake_local_gre_port1.id,
                network_id=2,
                network_type='gre')
        net_2_gre_ports = self.logical_networks.get_local_port_count(
                network_id=2,
                network_type='gre')
        self.assertEqual(1, net_2_gre_ports)
        self.logical_networks.remove_local_port(
                port_id=fake_local_gre_port1.id,
                network_id=2,
                network_type='gre')
        net_2_gre_ports = self.logical_networks.get_local_port_count(
                network_id=2,
                network_type='gre')
        self.assertEqual(0, net_2_gre_ports)

    def test_add_remove_remote_port(self):
        fake_remote_vlan_port1 = test_app_base.make_fake_remote_port(
                name='fake_remote_vlan_port1',
                unique_key=30,
                lswitch='fake_vlan_switch1')
        self.logical_networks.add_remote_port(
                port_id=fake_remote_vlan_port1.id,
                network_id=1,
                network_type='vlan')
        net_1_vlan_ports = self.logical_networks.get_remote_port_count(
                network_id=1,
                network_type='vlan')
        self.assertEqual(1, net_1_vlan_ports)
        fake_remote_vlan_port2 = test_app_base.make_fake_remote_port(
                name='fake_remote_vlan_port2',
                unique_key=4,
                lswitch='fake_vlan_switch1')
        self.logical_networks.add_remote_port(
                port_id=fake_remote_vlan_port2.id,
                network_id=1,
                network_type='vlan')
        net_1_vlan_ports = self.logical_networks.get_remote_port_count(
                network_id=1,
                network_type='vlan')
        self.assertEqual(2, net_1_vlan_ports)
        net_2_gre_ports = self.logical_networks.get_remote_port_count(
                network_id=2,
                network_type='gre')
        self.assertEqual(0, net_2_gre_ports)
        fake_local_gre_port1 = test_app_base.make_fake_remote_port(
                lswitch='fake_gre_switch1',
                name='fake_remote_gre_port1',
                unique_key=5)
        self.logical_networks.add_remote_port(
                port_id=fake_local_gre_port1.id,
                network_id=2,
                network_type='gre')
        net_2_gre_ports = self.logical_networks.get_remote_port_count(
                network_id=2,
                network_type='gre')

        self.assertEqual(1, net_2_gre_ports)
        self.logical_networks.remove_remote_port(
                port_id=fake_local_gre_port1.id,
                network_id=2,
                network_type='gre')
        net_2_gre_ports = self.logical_networks.get_remote_port_count(
                network_id=2,
                network_type='gre')
        self.assertEqual(0, net_2_gre_ports)
