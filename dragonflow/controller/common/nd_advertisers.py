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

from ryu.lib.packet import icmpv6
from ryu.lib.packet import in_proto
from ryu.ofproto import ether

from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils


class NeighAdvertiser(object):
    """
    A class for creating and removing Neighbor Advertisers (Neighbor Discovery)
    The class will match Neighbor Solicitation requests, and advertise
    the response.
    @param network_key The network's unique key in which the port exists
    @param interface_ip The port's IPv6 address
    @param interface_mac The port's physical address. Optional only in case
            of remove.
    """
    def __init__(self, app, network_key, interface_ip,
                 interface_mac=None, table_id=const.IPV6_ND_TABLE):
        self.app = app
        self.datapath = app.datapath
        self.network_key = network_key
        self.interface_ip = interface_ip
        self.mac_address = interface_mac
        self.table_id = table_id

    def _get_match(self):
        parser = self.datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IPV6)
        match.set_ip_proto(in_proto.IPPROTO_ICMPV6)
        match.set_ipv6_dst(utils.ipv6_text_to_short(self.interface_ip))
        match.set_icmpv6_type(icmpv6.ND_NEIGHBOR_SOLICIT)
        if self.network_key is not None:
            match.set_metadata(self.network_key)
        return match

    def _get_instructions(self):
        ofproto = self.datapath.ofproto
        parser = self.datapath.ofproto_parser
        actions = [
            parser.OFPActionSetField(icmpv6_type=icmpv6.ND_NEIGHBOR_ADVERT),
            parser.NXActionRegMove(src_field='ipv6_src',
                                   dst_field='ipv6_dst',
                                   n_bits=128),
            parser.NXActionRegMove(src_field='eth_src',
                                   dst_field='eth_dst',
                                   n_bits=48),
            parser.OFPActionSetField(eth_src=self.mac_address),
            parser.OFPActionSetField(ipv6_nd_sll=self.mac_address),
            parser.OFPActionOutput(ofproto.OFPP_IN_PORT, 0)]
        instructions = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return instructions

    def add(self):
        match = self._get_match()
        instructions = self._get_instructions()
        ofproto = self.datapath.ofproto
        self.app.mod_flow(table_id=self.table_id,
                          command=ofproto.OFPFC_ADD,
                          priority=const.PRIORITY_MEDIUM,
                          match=match,
                          inst=instructions,
                          flags=ofproto.OFPFF_SEND_FLOW_REM)

    def remove(self):
        ofproto = self.datapath.ofproto
        match = self._get_match()
        self.app.mod_flow(table_id=self.table_id,
                          command=ofproto.OFPFC_DELETE,
                          priority=const.PRIORITY_MEDIUM,
                          match=match)
