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
from oslo_log import log
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import ipv6
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow._i18n import _LE, _LI
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils
from dragonflow.controller.common import icmp_responder
from dragonflow.controller import df_base_app

LOG = log.getLogger(__name__)


class L3App(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(L3App, self).__init__(*args, **kwargs)
        self.idle_timeout = 30
        self.hard_timeout = 0
        self.api.register_table_handler(const.L3_LOOKUP_TABLE,
                self.packet_in_handler)
        self.use_active_detection_for_allowed_address_pairs = \
            utils.check_active_port_detection_app()

    def switch_features_handler(self, ev):
        self.add_flow_go_to_table(self.get_datapath(),
                                  const.L3_LOOKUP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.EGRESS_TABLE)

    def router_created(self, router):
        self._add_new_lrouter(router)

    def router_updated(self, router, original_router):
        if original_router is None:
            LOG.info(_LI("Logical Router created = %s"), router)
            self._add_new_lrouter(router)
            return

        self._update_router_interfaces(original_router, router)

    def router_deleted(self, router):
        for port in router.get_ports():
            self._delete_router_port(port)

    def _update_router_interfaces(self, old_router, new_router):
        new_router_ports = new_router.get_ports()
        old_router_ports = old_router.get_ports()
        for new_port in new_router_ports:
            if new_port not in old_router_ports:
                self._add_new_router_port(new_router, new_port)
            else:
                old_router_ports.remove(new_port)

        for old_port in old_router_ports:
            self._delete_router_port(old_port)

    def _add_new_lrouter(self, lrouter):
        for new_port in lrouter.get_ports():
            self._add_new_router_port(lrouter, new_port)

    def packet_in_handler(self, event):
        msg = event.msg

        pkt = packet.Packet(msg.data)
        pkt_ip = pkt.get_protocol(ipv4.ipv4)
        if pkt_ip is None:
            pkt_ip = pkt.get_protocol(ipv6.ipv6)

        if pkt_ip is None:
            LOG.error(_LE("Received Non IP Packet"))
            return

        network_id = msg.match.get('metadata')
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)
        try:
            self._get_route(pkt_ip, pkt_ethernet, network_id, msg)
        except Exception as e:
            LOG.error(_LE("L3 App PacketIn exception raised"))
            LOG.error(e)

    def _get_route(self, pkt_ip, pkt_ethernet, network_id, msg):
        ip_addr = netaddr.IPAddress(pkt_ip.dst)
        router = self.db_store.get_router_by_router_interface_mac(
            pkt_ethernet.dst)
        for router_port in router.get_ports():
            if ip_addr in netaddr.IPNetwork(router_port.get_network()):
                if str(ip_addr) == router_port.get_ip():
                    self._install_flow_send_to_output_table(
                        network_id,
                        router_port)
                    return
                dst_ports = self.db_store.get_ports_by_network_id(
                    router_port.get_lswitch_id())
                for out_port in dst_ports:
                    if out_port.get_ip() == pkt_ip.dst:
                        self._install_l3_flow(router_port,
                                              out_port.get_tunnel_key(),
                                              out_port.get_ip(),
                                              out_port.get_mac(),
                                              msg,
                                              network_id)
                        return

                # Only support to use active detection for allowed address
                #  pairs for now.
                if self.use_active_detection_for_allowed_address_pairs:
                    # if there is none port have this ip, try to find this ip
                    # among active nodes.
                    active_ports = \
                        self.db_store.get_active_ports_by_network_id(
                            router_port.get_lswitch_id())
                    for active_port in active_ports:
                        if active_port.get_ip() == pkt_ip.dst:
                            lport_id = active_port.get_detected_lport_id()
                            if lport_id is None:
                                # TODO(yuan wei) log error
                                continue
                            lport = self.db_store.get_local_port(lport_id)
                            if lport is None:
                                # TODO(yuan wei) log error
                                continue
                            self._install_l3_flow(
                                router_port,
                                lport.get_tunnel_key(),
                                active_port.get_ip(),
                                active_port.get_detected_mac(),
                                msg,
                                network_id)
                            return

    def _install_l3_flow(self, dst_router_port, dst_port_key, dst_ip, dst_mac,
                         msg, src_network_id):
        reg7 = dst_port_key
        src_mac = dst_router_port.get_mac()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        if netaddr.IPAddress(dst_ip).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=src_network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=src_network_id,
                                    ipv6_dst=dst_ip)

        actions = []
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(eth_src=src_mac))
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        actions.append(parser.OFPActionSetField(reg7=reg7))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=dst_router_port.get_tunnel_key(),
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match,
            idle_timeout=self.idle_timeout,
            hard_timeout=self.hard_timeout)

        in_port = msg.match.get('in_port')
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPPacketOut(datapath=self.get_datapath(),
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data)
        self.get_datapath().send_msg(out)

    def _add_new_router_port(self, router, router_port):
        LOG.info(_LI("Adding new logical router interface = %s"),
                 router_port)
        local_network_id = self.db_store.get_unique_key_by_id(
            'lswitchs', router_port.get_lswitch_id())
        datapath = self.get_datapath()
        if datapath is None:
            return

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        mac = router_port.get_mac()
        tunnel_key = router_port.get_tunnel_key()
        dst_ip = router_port.get_ip()

        # Add router ARP & ICMP responder for IPv4 Addresses
        is_ipv4 = netaddr.IPAddress(dst_ip).version == 4
        if is_ipv4:
            arp_responder.ArpResponder(
                self, local_network_id, dst_ip, mac).add()
            icmp_responder.ICMPResponder(self, dst_ip, mac).add()

        # If router interface IP, send to output table
        if is_ipv4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=local_network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=local_network_id,
                                    ipv6_dst=dst_ip)

        actions = []
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

        #add dst_mac=gw_mac l2 goto l3 flow
        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        goto_inst = parser.OFPInstructionGotoTable(const.L3_LOOKUP_TABLE)
        inst = [goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Match all possible routeable traffic and send to controller
        for port in router.get_ports():
            if port.get_id() != router_port.get_id():
                # From this router interface to all other interfaces
                self._add_subnet_send_to_controller(local_network_id,
                                                    port.get_cidr_network(),
                                                    port.get_cidr_netmask(),
                                                    port.get_tunnel_key())

                # From all the other interfaces to this new interface
                router_port_net_id = self.db_store.get_unique_key_by_id(
                    'lswitchs', port.get_lswitch_id())
                self._add_subnet_send_to_controller(
                    router_port_net_id,
                    router_port.get_cidr_network(),
                    router_port.get_cidr_netmask(),
                    tunnel_key)

    def _install_flow_send_to_output_table(self, network_id, router_port):
        dst_ip = router_port.get_ip()
        tunnel_key = router_port.get_tunnel_key()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        if netaddr.IPAddress(dst_ip).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=dst_ip)

        actions = []
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match,
            idle_timeout=self.idle_timeout,
            hard_timeout=self.hard_timeout)

    def _add_subnet_send_to_controller(self, network_id, dst_network,
                                       dst_netmask, dst_router_tunnel_key):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        if netaddr.IPAddress(dst_network).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=(dst_network, dst_netmask))
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=(dst_network, dst_netmask))

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            self.get_datapath(),
            cookie=dst_router_tunnel_key,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _delete_router_port(self, router_port):
        LOG.info(_LI("Removing logical router interface = %s"),
                 router_port)
        local_network_id = self.db_store.get_unique_key_by_id(
            'lswitchs', router_port.get_lswitch_id())
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        tunnel_key = router_port.get_tunnel_key()
        ip = router_port.get_ip()
        mac = router_port.get_mac()

        if netaddr.IPAddress(ip).version == 4:
            arp_responder.ArpResponder(
                self, local_network_id, ip).remove()
            icmp_responder.ICMPResponder(self, ip, mac).remove()

        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

        match = parser.OFPMatch()
        cookie = tunnel_key
        self.mod_flow(
            datapath=self.get_datapath(),
            cookie=cookie,
            cookie_mask=cookie,
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
