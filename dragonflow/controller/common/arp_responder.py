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

import struct

from ryu.lib import addrconv
from ryu.lib.packet import arp
from ryu.ofproto import ether

from dragonflow.controller.common import constants as const


class ArpResponder(object):
    """
    A class for creating and removing ARP responders.
    @param network_id The network ID in which the port exists
    @param interface_ip The port's IPv4 address
    @param interface_mac The port's physical address. Optional only in case
            of remove.
    """
    def __init__(self, datapath, network_id, interface_ip, interface_mac=None):
        self.datapath = datapath
        self.network_id = network_id
        self.interface_ip = interface_ip
        self.mac_address = interface_mac

    def get_match(self):
        parser = self.datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_tpa(self.ipv4_text_to_int(str(self.interface_ip)))
        match.set_arp_opcode(arp.ARP_REQUEST)
        match.set_metadata(self.network_id)
        return match

    def get_instructions(self):
        ofproto = self.datapath.ofproto
        parser = self.datapath.ofproto_parser
        actions = [parser.OFPActionSetField(arp_op=arp.ARP_REPLY),
                   parser.NXActionRegMove(src_field='arp_sha',
                                          dst_field='arp_tha',
                                          n_bits=48),
                   parser.NXActionRegMove(src_field='arp_spa',
                                          dst_field='arp_tpa',
                                          n_bits=32),
                   parser.OFPActionSetField(eth_src=self.mac_address),
                   parser.OFPActionSetField(arp_sha=self.mac_address),
                   parser.OFPActionSetField(arp_spa=self.interface_ip),
                   parser.OFPActionOutput(ofproto.OFPP_IN_PORT, 0)]
        instructions = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return instructions

    def add(self):
            match = self.get_match()
            instructions = self.get_instructions()
            ofproto = self.datapath.ofproto
            parser = self.datapath.ofproto_parser
            msg = parser.OFPFlowMod(datapath=self.datapath,
                                    table_id=const.ARP_TABLE,
                                    command=ofproto.OFPFC_ADD,
                                    priority=const.PRIORITY_MEDIUM,
                                    match=match, instructions=instructions,
                                    flags=ofproto.OFPFF_SEND_FLOW_REM)
            self.datapath.send_msg(msg)

    def remove(self):
        ofproto = self.datapath.ofproto
        parser = self.datapath.ofproto_parser
        match = self.get_match()
        msg = parser.OFPFlowMod(datapath=self.datapath,
                                cookie=0,
                                cookie_mask=0,
                                table_id=const.ARP_TABLE,
                                command=ofproto.OFPFC_DELETE,
                                priority=const.PRIORITY_MEDIUM,
                                out_port=ofproto.OFPP_ANY,
                                out_group=ofproto.OFPG_ANY,
                                match=match)
        self.datapath.send_msg(msg)

    def ipv4_text_to_int(self, ip_text):
        if ip_text == 0:
            return ip_text
        assert isinstance(ip_text, str)
        return struct.unpack('!I', addrconv.ipv4.text_to_bin(ip_text))[0]
