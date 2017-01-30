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
from ryu.lib.packet import ethernet
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow.controller.common import cookies
from dragonflow.controller.common import utils
from dragonflow.controller import df_db_notifier


class DFlowApp(df_db_notifier.DBNotifyInterface):
    def __init__(self, api, db_store=None, vswitch_api=None, nb_api=None):
        self.api = api
        self.db_store = db_store
        self.vswitch_api = vswitch_api
        self.nb_api = nb_api

    def update_local_port(self, lport, original_lport):
        """override update_local_port method to default call add_local_port
        method

        :param lport:           local logical port which is updated to db
        :param original_lport:  local logical port in db before the update
        """
        self.add_local_port(lport)

    def update_remote_port(self, lport, original_lport):
        """update remote logical port hook callback

        :param lport:           logical port which resides on other compute
        node, and is updated in db
        :param original_lport:  logical port in db which resides on other
        compute node before the update
        """
        self.add_remote_port(lport)

    @property
    def datapath(self):
        return self.api.datapath

    @property
    def parser(self):
        return self.datapath.ofproto_parser

    @property
    def ofproto(self):
        return self.datapath.ofproto

    @property
    def local_ports(self):
        return self.datapath.local_ports

    def add_flow_go_to_table(self, table, priority, goto_table_id,
                             datapath=None, match=None):

        if datapath is None:
            datapath = self.datapath

        inst = [datapath.ofproto_parser.OFPInstructionGotoTable(goto_table_id)]
        self.mod_flow(datapath, inst=inst, table_id=table,
                      priority=priority, match=match)

    def mod_flow(self, datapath=None, cookie=0, cookie_mask=0, table_id=0,
                 command=None, idle_timeout=0, hard_timeout=0,
                 priority=0xff, buffer_id=0xffffffff, match=None,
                 actions=None, inst_type=None, out_port=None,
                 out_group=None, flags=0, inst=None):

        if datapath is None:
            datapath = self.datapath

        if command is None:
            command = datapath.ofproto.OFPFC_ADD

        if inst is None:
            if inst_type is None:
                inst_type = datapath.ofproto.OFPIT_APPLY_ACTIONS

            inst = []
            if actions is not None:
                inst = [datapath.ofproto_parser.OFPInstructionActions(
                    inst_type, actions)]

        if out_port is None:
            out_port = datapath.ofproto.OFPP_ANY

        if out_group is None:
            out_group = datapath.ofproto.OFPG_ANY

        cookie, cookie_mask = utils.set_aging_cookie_bits(cookie, cookie_mask)

        message = datapath.ofproto_parser.OFPFlowMod(datapath, cookie,
                                                     cookie_mask,
                                                     table_id, command,
                                                     idle_timeout,
                                                     hard_timeout,
                                                     priority,
                                                     buffer_id,
                                                     out_port,
                                                     out_group,
                                                     flags,
                                                     match,
                                                     inst)

        datapath.send_msg(message)

    def send_packet(self, port, pkt):
        datapath = self.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=pkt)
        datapath.send_msg(out)

    def send_arp_request(self, src_mac, src_ip, dst_ip, port):
        arp_request_pkt = packet.Packet()
        arp_request_pkt.add_protocol(ethernet.ethernet(
                                     ethertype=ether.ETH_TYPE_ARP,
                                     src=src_mac))

        arp_request_pkt.add_protocol(arp.arp(
                                    src_mac=src_mac,
                                    src_ip=src_ip,
                                    dst_ip=dst_ip))

        self.send_packet(port, arp_request_pkt)

    def register_local_cookie_bits(self, name, length):
        cookies.register_cookie_bits(name, length,
                                     True, self.__class__.__name__)

    def get_local_cookie(self, name, value, old_cookie=0, old_mask=0):
        return cookies.get_cookie(name, value,
                                  old_cookie=old_cookie, old_mask=old_mask,
                                  is_local=True,
                                  app_name=self.__class__.__name__)
