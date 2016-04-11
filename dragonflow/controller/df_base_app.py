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

from dragonflow.controller.df_db_notifier import DBNotifyInterface
from oslo_log import log as logging
from ryu.lib.packet import arp
from ryu.lib.packet import ethernet
from ryu.lib.packet import packet
from ryu.ofproto import ether

LOG = logging.getLogger(__name__)


class DFlowApp(DBNotifyInterface):
    def __init__(self, api, db_store=None, vswitch_api=None, nb_api=None):
        self.api = api
        self.db_store = db_store
        self.vswitch_api = vswitch_api
        self.nb_api = nb_api

    def get_datapath(self):
        return self.api.datapath

    def add_flow_go_to_table(self, datapath,
            table, priority, goto_table_id, match=None):
        inst = [datapath.ofproto_parser.OFPInstructionGotoTable(goto_table_id)]
        self.mod_flow(datapath, inst=inst, table_id=table,
                      priority=priority, match=match)

    def mod_flow(self, datapath, cookie=0, cookie_mask=0, table_id=0,
                 command=None, idle_timeout=0, hard_timeout=0,
                 priority=0xff, buffer_id=0xffffffff, match=None,
                 actions=None, inst_type=None, out_port=None,
                 out_group=None, flags=0, inst=None):

        if command is None:
            command = datapath.ofproto.OFPFC_ADD

        if inst is None:
            if inst_type is None:
                inst_type = datapath.ofproto.OFPIT_APPLY_ACTIONS

            inst = []
            if actions is not None:
                inst = [datapath.ofproto_parser.OFPInstructionActions(
                    inst_type, actions)]

                if match is None:
                    match = datapath.ofproto_parser.OFPMatch()

        if out_port is None:
            out_port = datapath.ofproto.OFPP_ANY

        if out_group is None:
            out_group = datapath.ofproto.OFPG_ANY

        from dragonflow.controller.aging import set_aging_cookie_bits
        cookie = set_aging_cookie_bits(cookie)

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

    def send_packet(self, *args, **kwargs):
        datapath = self.get_datapath()
        self._send_packet(datapath, *args, **kwargs)

    def _send_packet(self, datapath, port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt.serialize()
        data = pkt.data
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
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
        arp_request_pkt.serialize()

        self._send_packet(self.get_datapath(), port, arp_request_pkt)
