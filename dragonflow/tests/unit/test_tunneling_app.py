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
from dragonflow.db.models import l2
from dragonflow.tests.unit import test_app_base


make_fake_local_port = test_app_base.make_fake_local_port
make_fake_remote_port = test_app_base.make_fake_remote_port


class TestTunnelingApp(test_app_base.DFAppTestBase):
    apps_list = ["tunneling"]

    def setUp(self):
        super(TestTunnelingApp, self).setUp()
        fake_gre_switch1 = l2.LogicalSwitch(
                subnets=test_app_base.fake_lswitch_default_subnets,
                mtu=1464,
                unique_key=6,
                topic='fake_tenant1',
                is_external=False,
                segmentation_id=410,
                name='private',
                network_type='gre',
                id='fake_gre_switch1')
        self.controller.update(fake_gre_switch1)
        self.app = self.open_flow_app.dispatcher.apps['tunneling']

    def test_tunneling_for_local_port(self):
        fake_local_gre_port1 = make_fake_local_port(
                lswitch='fake_gre_switch1')
        match = self.app.parser.OFPMatch(tunnel_id_nxm=410,
                                         in_port=11)
        actions = [self.app.parser.OFPActionSetField(metadata=21)]
        inst = [self.app.parser.OFPInstructionActions(
            self.app.ofproto.OFPIT_APPLY_ACTIONS, actions),
                self.app.parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)]
        self.controller.update(fake_local_gre_port1)
        self.app.mod_flow.assert_called_with(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self.app.mod_flow.reset_mock()

        fake_local_gre_port2 = make_fake_local_port(
                lswitch='fake_gre_switch1',
                macs=['1a:0b:0c:0d:0e:0f'],
                ips=['10.0.0.12'])
        self.controller.update(fake_local_gre_port2)
        self.app.mod_flow.assert_not_called()
        self.app.mod_flow.reset_mock()

    def test_multicast_flow_for_remote_port(self):
        fake_remote_gre_port1 = make_fake_remote_port(
                lswitch='fake_gre_switch1',
                name='fake_remote_gre_port1')
        remote_ip = fake_remote_gre_port1.binding.ip
        match = self.app._make_bum_match(metadata=21)
        actions = [
                self.app.parser.OFPActionSetField(
                    tun_ipv4_dst=remote_ip),
                self.app.parser.OFPActionSetField(
                    tunnel_id_nxm=410),
                self.app.parser.OFPActionOutput(port=7)]
        self.vswitch_api.get_vtp_ofport.return_value = 7
        self.controller.update(fake_remote_gre_port1)
        self.app.parser.OFPInstructionActions.assert_called_with(
            self.app.ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [self.app.parser.OFPInstructionActions()]
        self.app.parser.OFPInstructionActions.reset_mock()
        self.app.mod_flow.assert_called_with(
            inst=inst,
            command=self.datapath.ofproto.OFPFC_ADD,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)
        self.app.mod_flow.reset_mock()

        fake_remote_gre_port2 = make_fake_remote_port(
                lswitch='fake_gre_switch1',
                binding=test_app_base.chassis_binding('fake_host2'),
                name='fake_remote_gre_port2')
        self.controller.update(fake_remote_gre_port2)
        self.app.parser.OFPInstructionActions.assert_called_with(
            self.app.ofproto.OFPIT_APPLY_ACTIONS, actions)
        self.app.parser.OFPInstructionActions.reset_mock()
        # The multicast flow will be modified to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_MODIFY,
            priority=const.PRIORITY_LOW,
            match=match)
        self.app.mod_flow.reset_mock()
        self.controller.delete(fake_remote_gre_port1)
        self.app.parser.OFPInstructionActions.assert_called_with(
            self.app.ofproto.OFPIT_APPLY_ACTIONS, actions)
        self.app.parser.OFPInstructionActions.reset_mock()
        # The multicast flow will be modified to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_MODIFY,
            priority=const.PRIORITY_LOW,
            match=match)
        self.app.mod_flow.reset_mock()

        self.controller.delete(fake_remote_gre_port2)
        # The multicast flow will be deleted to EGRESS_TABLE with priority low
        self.app.mod_flow.assert_called_with(
            inst=None,
            table_id=const.EGRESS_TABLE,
            command=self.datapath.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=match)
        self.app.mod_flow.reset_mock()
