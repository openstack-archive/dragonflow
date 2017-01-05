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


class TestTunnelingApp(test_app_base.DFAppTestBase):
    apps_list = "tunneling_app.TunnelingApp"

    def setUp(self):
        super(TestTunnelingApp, self).setUp()
        fake_gre_switch1 = make_fake_logic_switch(
                subnets=test_app_base.fake_lswitch_default_subnets,
                mtu=1464,
                unique_key=6,
                topic='fake_tenant1',
                router_external=False,
                segmentation_id=410,
                name='private',
                network_type='gre',
                id='fake_gre_switch1')
        self.controller.update_lswitch(fake_gre_switch1)
        self.app = self.open_flow_app.dispatcher.apps[0]

    def test_tunneling_for_local_port(self):
        fake_local_gre_port1 = make_fake_local_port(network_type='gre',
                lswitch='fake_gre_switch1')
        self.controller.update_lport(fake_local_gre_port1)
        self.app.mod_flow.assert_called_with(
            inst=mock.ANY,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

        fake_local_gre_port2 = make_fake_local_port(network_type='gre',
                lswitch='fake_gre_switch1',
                macs=['1a:0b:0c:0d:0e:0f'],
                ips=['10.0.0.12'],
                ofport=2)
        self.controller.update_lport(fake_local_gre_port2)
        self.app.mod_flow.assert_not_called()
        self.app.mod_flow.reset_mock()

    def test_multicast_flow_for_remote_port(self):
        fake_remote_gre_port1 = make_fake_remote_port(network_type='gre',
                lswitch='fake_gre_switch1',
                chassis='fake_host2',
                name='fake_remote_gre_port1')

        self.controller.update_lport(fake_remote_gre_port1)
        self.app.mod_flow.assert_called_with(
            inst=mock.ANY,
            command=self.datapath.ofproto.OFPFC_ADD,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

        fake_remote_gre_port2 = make_fake_remote_port(network_type='gre',
                lswitch='fake_gre_switch1',
                chassis='fake_host2',
                name='fake_remote_gre_port2')
        self.controller.update_lport(fake_remote_gre_port2)
        # The multicast flow will be modified to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            inst=mock.ANY,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_MODIFY,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()
        self.controller.delete_lport(fake_remote_gre_port1.get_id())
        # The multicast flow will be modified to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            inst=mock.ANY,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_MODIFY,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

        self.controller.delete_lport(fake_remote_gre_port2.get_id())
        # The multicast flow will be deleted to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            inst=None,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
