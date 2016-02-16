# Copyright (c) 2015 OpenStack Foundation.
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
from dragonflow.controller.df_base_app import DFlowApp
from ryu.ofproto import ether

CT_STATE_NEW = 0x01
CT_STATE_EST = 0x02
CT_STATE_REL = 0x04
CT_STATE_RPL = 0x08
CT_STATE_INV = 0x10
CT_STATE_TRK = 0x20
METADATA_REG = 0x80000408
CT_ZONE_REG = 0x1d402
CT_FLAG_COMMIT = 1
CT_STATE_MASK = 0x3f


class SGApp(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(SGApp, self).__init__(*args, **kwargs)
        # TODO(dingbo) local cache related to specific implementation

    def switch_features_handler(self, ev):
        if self.get_datapath() is None:
            return
        # add default drop flow
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        #pre ct zone
        actions = []
        actions.append(parser.NXActionCT(actions=[], alg=0, flags=0,
            recirc_table=const.EGRESS_CONNTRACK_TABLE, zone_ofs_nbits=15,
            zone_src=METADATA_REG))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_PRE_CONNTRACK_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        actions = []
        actions.append(parser.NXActionCT(actions=[], alg=0, flags=0,
            recirc_table=const.INGRESS_CONNTRACK_TABLE, zone_ofs_nbits=15,
            zone_src=METADATA_REG))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_PRE_CONNTRACK_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # est state, pass
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_EST, CT_STATE_MASK))
        goto_inst = parser.OFPInstructionGotoTable(
                    const.SERVICES_CLASSIFICATION_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        goto_inst = parser.OFPInstructionGotoTable(
                    const.INGRESS_DISPATCH_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # rel state, pass
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_REL, CT_STATE_MASK))
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        goto_inst = parser.OFPInstructionGotoTable(
                    const.INGRESS_DISPATCH_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # inv state, drop
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_INV, CT_STATE_MASK))
        self.mod_flow(
             self.get_datapath(),
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # new state, goto security group table
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_NEW, CT_STATE_MASK))
        goto_inst = parser.OFPInstructionGotoTable(
                    const.EGRESS_SECURITY_GROUP_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        goto_inst = parser.OFPInstructionGotoTable(
                    const.INGRESS_SECURITY_GROUP_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # defaults to drop packet
        self.mod_flow(
             self.get_datapath(),
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_DEFAULT)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_DEFAULT)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.EGRESS_SECURITY_GROUP_TABLE,
             priority=const.PRIORITY_DEFAULT)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.INGRESS_SECURITY_GROUP_TABLE,
             priority=const.PRIORITY_DEFAULT)

    def remove_local_port(self, lport):

        # TODO(dingbo) remove SG related flow
        pass

    def remove_remote_port(self, lport):

        # TODO(dingbo) modify SG related flow
        pass

    def add_local_port(self, lport):

        # TODO(dingbo) add SG related flow
        pass

    def add_remote_port(self, lport):

        # TODO(dingbo) modify SG related flow
        pass

    def add_security_group_rule(self, secgroup, secgroup_rule):

        # TODO(dingbo) modify SG related flow
        pass

    def remove_security_group_rule(self, secgroup, secgroup_rule):

        # TODO(dingbo) modify SG related flow
        pass
