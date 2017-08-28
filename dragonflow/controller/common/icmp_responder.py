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
    @param app The application that initiates this class.
    @param interface_ip The port's IPv4 address.
    @param router_key The unique key of router. Specify this param when icmp
                      echo request targets to router interface.
    @param dst_mac The dst mac of icmp echo request. Specify this param when
                   icmp echo request's src and dst are in same L2 domain.
                   dst_mac has higher priority than router_key when both of
                   them are specified.
    @param table_id Where the respondor will be installed.
    """
    def __init__(self, app, interface_ip, router_key=None, dst_mac=None,
                 table_id=const.L3_LOOKUP_TABLE, network_id=None):
        self.app = app
        self.datapath = app.datapath
        self.interface_ip = interface_ip
        self.router_key = router_key
        self.dst_mac = dst_mac
        self.table_id = table_id
        self.network_id = network_id

    def _get_match(self):
        parser = self.datapath.ofproto_parser
        match_fields = {'eth_type': ether.ETH_TYPE_IP,
                        'ip_proto': in_proto.IPPROTO_ICMP,
                        'ipv4_dst': self.interface_ip,
                        'icmpv4_type': icmp.ICMP_ECHO_REQUEST}
        if self.dst_mac:
            match_fields.update({'eth_dst': self.dst_mac})
        elif self.router_key:
            match_fields.update({'reg5': self.router_key})
        if self.network_id is not None:
            match_fields['metadata'] = self.network_id

        match = parser.OFPMatch(**match_fields)
        return match

    def _get_instructions(self):
        ofproto = self.datapath.ofproto
        parser = self.datapath.ofproto_parser

        if self.dst_mac:
            actions = [parser.NXActionRegMove(src_field='eth_src',
                                              dst_field='eth_dst',
                                              n_bits=48),
                       parser.OFPActionSetField(eth_src=self.dst_mac)]
        else:
            # Switch eth_dst and eth_src
            actions = [parser.NXActionRegMove(src_field='eth_dst',
                                              dst_field='metadata',
                                              n_bits=48),
                       parser.NXActionRegMove(src_field='eth_src',
                                              dst_field='eth_dst',
                                              n_bits=48),
                       parser.NXActionRegMove(src_field='metadata',
                                              dst_field='eth_src',
                                              n_bits=48)]

        actions += [parser.NXActionRegMove(src_field='ipv4_src',
                                           dst_field='ipv4_dst',
                                           n_bits=32),
                    parser.OFPActionSetField(ipv4_src=self.interface_ip),
                    # Refresh the ttl of reply packet.
                    parser.OFPActionSetNwTtl(64),
                    parser.OFPActionSetField(icmpv4_type=icmp.ICMP_ECHO_REPLY),
                    parser.OFPActionSetField(
                        icmpv4_code=icmp.ICMP_ECHO_REPLY_CODE),
                    parser.NXActionRegMove(src_field='reg6',
                                           dst_field='reg7',
                                           n_bits=32)]

        instructions = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
            parser.OFPInstructionGotoTable(const.INGRESS_DISPATCH_TABLE),
        ]
        return instructions

    def add(self, **kwargs):
        match = self._get_match()
        instructions = self._get_instructions()
        ofproto = self.datapath.ofproto
        self.app.mod_flow(
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
            table_id=self.table_id,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match)
