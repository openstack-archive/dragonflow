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

from ryu.lib.packet import arp
from ryu.ofproto import ether

from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils


class ArpResponder(object):
    """
    A class for creating and removing ARP responders.
    @param network_id The network ID in which the port exists
    @param interface_ip The port's IPv4 address
    @param interface_mac The port's physical address. Optional only in case
            of remove.
    @param table_id The table to install the ARP responder at.
    @param priority Priority of the installed responder flows.
    @param goto_table_id The table that will receive the response.
    """
    def __init__(self, app, network_id, interface_ip,
                 interface_mac=None, table_id=const.ARP_TABLE,
                 priority=const.PRIORITY_MEDIUM,
                 goto_table_id=const.INGRESS_DISPATCH_TABLE):
        self.app = app
        self.datapath = app.datapath
        self.network_id = network_id
        self.interface_ip = interface_ip
        self.mac_address = interface_mac
        self.table_id = table_id
        self.priority = priority
        self.goto_table_id = goto_table_id

    def _get_match(self):
        parser = self.datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_tpa(utils.ipv4_text_to_int(str(self.interface_ip)))
        match.set_arp_opcode(arp.ARP_REQUEST)
        if self.network_id is not None:
            match.set_metadata(self.network_id)
        return match

    def _get_instructions(self):
        ofproto = self.datapath.ofproto
        parser = self.datapath.ofproto_parser
        actions = [parser.OFPActionSetField(arp_op=arp.ARP_REPLY),
                   parser.NXActionRegMove(src_field='arp_sha',
                                          dst_field='arp_tha',
                                          n_bits=48),
                   parser.NXActionRegMove(src_field='arp_spa',
                                          dst_field='arp_tpa',
                                          n_bits=32),
                   parser.NXActionRegMove(src_field='eth_src',
                                          dst_field='eth_dst',
                                          n_bits=48),
                   parser.OFPActionSetField(eth_src=self.mac_address),
                   parser.OFPActionSetField(arp_sha=self.mac_address),
                   parser.OFPActionSetField(arp_spa=self.interface_ip),
                   parser.NXActionRegMove(src_field='reg6',
                                          dst_field='reg7',
                                          n_bits=32)]

        need_resubmit = self.table_id >= self.goto_table_id

        if need_resubmit:
            actions.append(
                parser.NXActionResubmitTable(table_id=self.goto_table_id))

        instructions = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
        ]

        # If we don't resubmit we can use a goto
        if not need_resubmit:
            instructions.append(
                parser.OFPInstructionGotoTable(self.goto_table_id))

        return instructions

    def add(self):
        match = self._get_match()
        instructions = self._get_instructions()
        ofproto = self.datapath.ofproto
        self.app.mod_flow(
                table_id=self.table_id,
                command=ofproto.OFPFC_ADD,
                priority=self.priority,
                match=match,
                flags=ofproto.OFPFF_SEND_FLOW_REM,
                inst=instructions)

    def remove(self):
        ofproto = self.datapath.ofproto
        match = self._get_match()
        self.app.mod_flow(
                table_id=self.table_id,
                command=ofproto.OFPFC_DELETE_STRICT,
                priority=self.priority,
                match=match)
