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

from ryu.lib.packet import icmp
from ryu.lib.packet import in_proto
from ryu.ofproto import ether

from dragonflow.controller.common import constants as const


class ICMPResponder(object):
    """
    A class for creating and removing ICMP responders.
    @param interface_ip The port's IPv4 address
    @param dst_mac The destination MAC address of packet
    """
    def __init__(self, app, interface_ip, dst_mac,
                 table_id=const.L2_LOOKUP_TABLE):
        self.app = app
        self.datapath = app.get_datapath()
        self.interface_ip = interface_ip
        self.dst_mac = dst_mac
        self.table_id = table_id

    def _get_match(self):
        parser = self.datapath.ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                eth_dst=self.dst_mac,
                                ip_proto=in_proto.IPPROTO_ICMP,
                                ipv4_dst=self.interface_ip,
                                icmpv4_type=icmp.ICMP_ECHO_REQUEST)
        return match

    def _get_instructions(self):
        ofproto = self.datapath.ofproto
        parser = self.datapath.ofproto_parser
        actions = [parser.NXActionRegMove(src_field='eth_src',
                                          dst_field='eth_dst',
                                          n_bits=48),
                   parser.NXActionRegMove(src_field='ipv4_src',
                                          dst_field='ipv4_dst',
                                          n_bits=32),
                   parser.OFPActionSetField(icmpv4_type=icmp.ICMP_ECHO_REPLY),
                   parser.OFPActionSetField(
                       icmpv4_code=icmp.ICMP_ECHO_REPLY_CODE),
                   parser.OFPActionSetField(eth_src=self.dst_mac),
                   parser.OFPActionSetField(ipv4_src=self.interface_ip),
                   parser.OFPActionOutput(ofproto.OFPP_IN_PORT, 0)]

        if self.table_id == const.L3_LOOKUP_TABLE:
            # There is an implicitly route if icmp responder is at
            # L3_LOOKUP_TABLE. A route should consume 1 ttl.
            actions.insert(0, parser.OFPActionDecNwTtl())

        instructions = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return instructions

    def add(self, **kwargs):
        match = self._get_match()
        instructions = self._get_instructions()
        ofproto = self.datapath.ofproto
        self.app.mod_flow(
            datapath=self.datapath,
            table_id=self.table_id,
            command=ofproto.OFPFC_ADD,
            priority=const.PRIORITY_VERY_HIGH,
            match=match,
            inst=instructions,
            **kwargs)

    def remove(self):
        ofproto = self.datapath.ofproto
        match = self._get_match()
        self.app.mod_flow(
            datapath=self.datapath,
            table_id=self.table_id,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match)
