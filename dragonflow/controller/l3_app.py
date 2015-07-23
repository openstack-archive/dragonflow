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

import netaddr

from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet
from ryu.ofproto import ether
from ryu.ofproto import ofproto_v1_3

from dragonflow.controller.df_base_app import DFlowApp

from oslo_log import log

from neutron.i18n import _LI, _LE


LOG = log.getLogger(__name__)

# TODO(gsagie) currently the number set in Ryu for this
# (OFPP_IN_PORT) is not working, use this until resolved
OF_IN_PORT = 0xfff8


class L3App(DFlowApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(L3App, self).__init__(*args, **kwargs)
        self.dp = None
        self.idle_timeout = 30
        self.hard_timeout = 30
        self.db_store = kwargs['db_store']

    def start(self):
        super(L3App, self).start()
        return 1

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        self.dp = ev.msg.datapath
        self.send_port_desc_stats_request(self.dp)
        self.add_flow_go_to_table(self.dp, 20, 1, 64)

    def send_port_desc_stats_request(self, datapath):
        ofp_parser = datapath.ofproto_parser
        req = ofp_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status_handler(self, ev):
        msg = ev.msg
        reason = msg.reason
        port_no = msg.desc.port_no
        datapath = ev.msg.datapath

        ofproto = msg.datapath.ofproto
        if reason == ofproto.OFPPR_ADD:
            LOG.info(_LI("port added %s"), port_no)
        elif reason == ofproto.OFPPR_DELETE:
            LOG.info(_LI("port deleted %s"), port_no)
        elif reason == ofproto.OFPPR_MODIFY:
            LOG.info(_LI("port modified %s"), port_no)
        else:
            LOG.info(_LI("Illeagal port state %(port_no)s %(reason)s")
                     % {'port_no': port_no, 'reason': reason})
        LOG.info(_LI(" Updating flow table on agents got port update "))
        if self.dp:
            self.send_port_desc_stats_request(datapath)
            if reason == ofproto.OFPPR_DELETE:
                pass

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        pass

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def OF_packet_in_handler(self, event):
        msg = event.msg

        pkt = packet.Packet(msg.data)
        is_ipv4_packet = pkt.get_protocol(ipv4.ipv4) is not None
        if is_ipv4_packet is None:
            LOG.error(_LE("Received IPv6 packet in controller, "
                          "currently only IPv4 is supported"))
            return

        network_id = msg.match.get('metadata')
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        # TODO(gsagie) encapsulate this in get_route method once done
        ip_addr = netaddr.IPAddress(pkt_ipv4.dst)
        router = self.db_store.get_router_by_router_interface_mac(
            pkt_ethernet.dst)
        for router_port in router.get_ports():
            if ip_addr in netaddr.IPNetwork(router_port.get_network()):
                if str(ip_addr) == router_port.get_ip():
                    self._install_flow_send_to_output_table(
                        network_id,
                        router_port.get_ip())
                    return
                dst_ports = self.db_store.get_ports_by_network_id(
                    router_port.get_network_id())
                for out_port in dst_ports:
                    if out_port.get_ip() == pkt_ipv4.dst:
                        self._install_l3_flow(router_port,
                                              out_port, msg,
                                              network_id)
                        return

    def _install_l3_flow(self, dst_router_port, dst_port, msg,
                         src_network_id):
        reg7 = dst_port.get_tunnel_key()
        dst_ip = dst_port.get_ip()
        src_mac = dst_router_port.get_mac()
        dst_mac = dst_port.get_mac()

        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(src_network_id)
        match.set_ipv4_dst(self.ipv4_text_to_int(str(dst_ip)))

        actions = []
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(eth_src=src_mac))
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        actions.append(parser.OFPActionSetField(reg7=reg7))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(64)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=20,
            priority=300,
            match=match,
            idle_timeout=self.idle_timeout,
            hard_timeout=self.hard_timeout)

        in_port = msg.match.get('in_port')
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPPacketOut(datapath=self.dp, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        self.dp.send_msg(out)

    def add_new_router_port(self, router, lport, router_port):

        if self.dp is None:
            return

        # TODO(gsagie) check what happens when external gateway port added

        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        network_id = lport.get_external_value('local_network_id')
        mac = lport.get_mac()
        tunnel_key = lport.get_tunnel_key()

        # Change destination classifier for router port to go to L3 table
        # Increase priority so L3 traffic is matched faster
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = []
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(20)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=17,
            command=ofproto.OFPFC_MODIFY,
            priority=200,
            match=match)

        # If router interface IP, send to output table
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(network_id)
        dst_ip = router_port.get_ip()
        match.set_ipv4_dst(self.ipv4_text_to_int(dst_ip))
        goto_inst = parser.OFPInstructionGotoTable(64)
        inst = [goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=20,
            priority=200,
            match=match)

        # Match all possible routeable traffic and send to controller
        for port in router.get_ports():
            if port.get_name() != router_port.get_name():
                # From this router interface to all other interfaces
                self._add_subnet_send_to_controller(network_id,
                                                    port.get_cidr_network(),
                                                    port.get_cidr_netmask())

                # From all the other interfaces to this new interface
                router_port_net_id = self.db_store.get_network_id(
                    port.get_network_id())
                self._add_subnet_send_to_controller(
                    router_port_net_id,
                    router_port.get_cidr_network(),
                    router_port.get_cidr_netmask())

    def _install_flow_send_to_output_table(self, network_id, dst_ip):
        parser = self.dp.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(network_id)
        match.set_ipv4_dst(self.ipv4_text_to_int(dst_ip))
        goto_inst = parser.OFPInstructionGotoTable(64)
        inst = [goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=20,
            priority=200,
            match=match,
            idle_timeout=self.idle_timeout,
            hard_timeout=self.hard_timeout)

    def _add_subnet_send_to_controller(self, network_id, dst_network,
                                       dst_netmask):
        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(network_id)
        match.set_ipv4_dst_masked(dst_network,
                                  dst_netmask)

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=20,
            priority=100,
            match=match)

    def delete_router_port(self, router_port, local_network_id):

        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        message = parser.OFPFlowMod(
            datapath=self.dp,
            cookie=0,
            cookie_mask=0,
            table_id=20,
            command=ofproto.OFPFC_DELETE,
            priority=100,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self.dp.send_msg(message)

        dst_network = router_port.get_cidr_network()
        dst_netmask = router_port.get_cidr_netmask()
        match = parser.OFPMatch()
        match.set_ipv4_dst_masked(dst_network,
                                  dst_netmask)
        message = parser.OFPFlowMod(
            datapath=self.dp,
            cookie=0,
            cookie_mask=0,
            table_id=20,
            command=ofproto.OFPFC_DELETE,
            priority=100,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self.dp.send_msg(message)
