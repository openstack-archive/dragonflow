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

from dragonflow.controller.common import constants as const
from dragonflow.tests.unit import test_app_base
import mock


make_fake_local_port = test_app_base.make_fake_local_port
make_fake_logic_switch = test_app_base.make_fake_logic_switch
make_fake_remote_port = test_app_base.make_fake_remote_port


class TestProviderNetsApp(test_app_base.DFAppTestBase):
    apps_list = "provider_networks_app.ProviderNetworksApp"

    def setUp(self):
        super(TestProviderNetsApp, self).setUp()
        fake_vlan_switch1 = make_fake_logic_switch(
                subnets=test_app_base.fake_lswitch_default_subnets,
                network_type='vlan',
                id='fake_vlan_switch1',
                mtu=1454,
                physical_network='phynet',
                router_external=False,
                unique_key=6,
                topic='fake_tenant1',
                segmentation_id=10,
                name='private')
        self.controller.update_lswitch(fake_vlan_switch1)
        self.app = self.open_flow_app.dispatcher.apps[0]
        self.app.ofproto.OFPVID_PRESENT = 0x1000

    def test_provider_vlan_port(self):
        fake_local_vlan_port1 = make_fake_local_port(network_type='vlan',
                lswitch='fake_vlan_switch1')
        self.app.int_ofports['phynet'] = 1
        self.controller.update_lport(fake_local_vlan_port1)
        self.app.mod_flow.assert_called_with(
            inst=mock.ANY,
            match=mock.ANY,
            priority=const.PRIORITY_HIGH,
            table_id=const.EGRESS_EXTERNAL_TABLE)
        self.app.mod_flow.reset_mock()

        fake_local_vlan_port2 = make_fake_local_port(network_type='vlan',
                lswitch='fake_vlan_switch1',
                macs=['1a:0b:0c:0d:0f:0f'],
                ips=['10.0.0.112'],
                ofport=12)
        self.controller.update_lport(fake_local_vlan_port2)
        self.app.mod_flow.assert_not_called()
        self.app.mod_flow.reset_mock()

        self.controller.delete_lport(fake_local_vlan_port1.get_id())
        self.app.mod_flow.assert_not_called()
        self.app.mod_flow.reset_mock()

        self.controller.delete_lport(fake_local_vlan_port2.get_id())
        self.app.mod_flow.assert_called_with(
            command=self.app.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_EXTERNAL_TABLE,
            priority=const.PRIORITY_HIGH,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()
