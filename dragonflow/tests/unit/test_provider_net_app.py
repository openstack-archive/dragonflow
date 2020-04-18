# Copyright (c) 2017 OpenStack Foundation.
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
from unittest import mock

from dragonflow.common import constants
from dragonflow.controller.common import constants as const
from dragonflow.db.models import l2
from dragonflow.db.models import switch
from dragonflow.tests.unit import test_app_base


make_fake_local_port = test_app_base.make_fake_local_port
make_fake_remote_port = test_app_base.make_fake_remote_port


class TestProviderNetsApp(test_app_base.DFAppTestBase):
    apps_list = ["provider"]

    def setUp(self):
        super(TestProviderNetsApp, self).setUp()
        self.fake_vlan_switch1 = l2.LogicalSwitch(
                network_type='vlan',
                id='fake_vlan_switch1',
                mtu=1454,
                physical_network='phynet',
                is_external=False,
                unique_key=6,
                topic='fake_tenant1',
                segmentation_id=10,
                name='private')
        fake_vlan_subnet = copy.deepcopy(
            test_app_base.fake_lswitch_default_subnets[0])
        fake_vlan_subnet.id = 'fake_vlan_subnet1'
        fake_vlan_subnet.lswitch = 'fake_vlan_switch1'
        self.controller.update(self.fake_vlan_switch1)
        self.controller.update(fake_vlan_subnet)
        self.app = self.open_flow_app.dispatcher.apps['provider']
        self.app.ofproto.OFPVID_PRESENT = 0x1000

    def test_provider_vlan_port(self):
        fake_local_vlan_port1 = make_fake_local_port(
                lswitch='fake_vlan_switch1')
        self.app.int_ofports['phynet'] = 1
        self.app.bridge_macs['phynet'] = '00:12:23:34:45:56'
        self.app.mod_flow.reset_mock()
        self.controller.update(fake_local_vlan_port1)
        match = self.app.parser.OFPMatch(metadata=21)
        actions = [
                self.app.parser.OFPActionOutput(
                    self.app.int_ofports['phynet'],
                    self.app.ofproto.OFPCML_NO_BUFFER)]
        inst = [self.app.parser.OFPInstructionActions(
                self.app.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.app.mod_flow.assert_called_with(
            inst=inst,
            match=match,
            priority=const.PRIORITY_HIGH,
            table_id=const.EGRESS_EXTERNAL_TABLE)
        self.app.mod_flow.reset_mock()

        fake_local_vlan_port2 = make_fake_local_port(
                lswitch='fake_vlan_switch1',
                macs=['1a:0b:0c:0d:0f:0f'],
                ips=['10.0.0.112'])
        self.controller.update(fake_local_vlan_port2)
        self.app.mod_flow.assert_not_called()
        self.app.mod_flow.reset_mock()

        self.controller.delete(fake_local_vlan_port1)
        self.app.mod_flow.assert_not_called()
        self.app.mod_flow.reset_mock()

        self.controller.delete(fake_local_vlan_port2)
        self.app.mod_flow.assert_called_with(
            command=self.app.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_EXTERNAL_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)
        self.app.mod_flow.reset_mock()

    def test_provider_bridge(self):
        self.app.int_ofports['phynet'] = 1
        self.app.bridge_macs['phynet'] = '00:12:23:34:45:56'
        self.app.reverse_bridge_mappings['private'] = 'phynet'

        fake_local_vlan_port = make_fake_local_port(
            lswitch='fake_vlan_switch1')
        self.controller.update(fake_local_vlan_port)
        self.app.mod_flow.reset_mock()

        switch_port = switch.SwitchPort(
            id='fake_switch_port', lport=fake_local_vlan_port.id,
            port_num=1, admin_state='up', name='private',
            mac_in_use='00:00:00:00:00:01',
            type=constants.SWITCH_COMPUTE_INTERFACE)
        self.controller.update(switch_port)

        call_list = [
            mock.call(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=const.EGRESS_EXTERNAL_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch()),
            mock.call(
                table_id=const.EGRESS_EXTERNAL_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(),
                inst=[self.app.parser.OFPInstructionActions()]
            )]
        self.assertEqual(len(call_list), self.app.mod_flow.call_count)
        self.app.mod_flow.assert_has_calls(call_list)

        self.app.mod_flow.reset_mock()
        self.controller.delete(switch_port)
        self.app.mod_flow.assert_called_with(
            command=self.app.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_EXTERNAL_TABLE,
            priority=const.PRIORITY_HIGH,
            match=self.app.parser.OFPMatch())
