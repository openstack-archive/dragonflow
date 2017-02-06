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
from neutron_lib import constants as common_const
from oslo_log import log
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import ethernet
from ryu.lib.packet import icmp
from ryu.lib.packet import in_proto
from ryu.lib.packet import ipv4
from ryu.lib.packet import ipv6
from ryu.lib.packet import packet
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
from ryu.ofproto import ether

from dragonflow._i18n import _LE, _LI, _LW
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import icmp_error_generator
from dragonflow.controller.common import icmp_responder
from dragonflow.controller import df_base_app
from dragonflow.db import models

LOG = log.getLogger(__name__)


# REVIST(xiaohhui): This is a randomly chosen number. Should this be unique
# for each router port?
ROUTER_PORT_BUFFER_ID = 0xff12


class L3App(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(L3App, self).__init__(*args, **kwargs)
        self.idle_timeout = 30
        self.hard_timeout = 0
        self.router_port_rarp_cache = {}
        self.conf = cfg.CONF.df_l3_app
        self.ttl_invalid_handler_rate_limit = df_utils.RateLimiter(
            max_rate=self.conf.router_ttl_invalid_max_rate,
            time_unit=1)
        self.port_icmp_unreach_respond_rate_limit = df_utils.RateLimiter(
            max_rate=self.conf.router_port_unreach_max_rate,
            time_unit=1)
        self.api.register_table_handler(const.L3_LOOKUP_TABLE,
                                        self.packet_in_handler)

    def switch_features_handler(self, ev):
        self.router_port_rarp_cache.clear()

    def router_updated(self, router, original_router):
        if not original_router:
            LOG.info(_LI("Logical Router created = %s"), router)
            self._add_new_lrouter(router)
            return

        self._update_router_interfaces(original_router, router)

    def router_deleted(self, router):
        for port in router.get_ports():
            self._delete_router_port(router, port)

    def _update_router_interfaces(self, old_router, new_router):
        new_router_ports = new_router.get_ports()
        old_router_ports = old_router.get_ports()
        for new_port in new_router_ports:
            if new_port not in old_router_ports:
                self._add_new_router_port(new_router, new_port)
            else:
                old_router_ports.remove(new_port)

        for old_port in old_router_ports:
            self._delete_router_port(new_router, old_port)

    def _add_new_lrouter(self, lrouter):
        for new_port in lrouter.get_ports():
            self._add_new_router_port(lrouter, new_port)

    def packet_in_handler(self, event):
        msg = event.msg
        pkt = packet.Packet(msg.data)

        if msg.reason == self.ofproto.OFPR_INVALID_TTL:
            LOG.debug("Get an invalid TTL packet at table %s",
                      const.L3_LOOKUP_TABLE)
            if self.ttl_invalid_handler_rate_limit():
                LOG.warning(
                    _LW("Get more than %(rate)s TTL invalid "
                        "packets per second at table %(table)s"),
                    {'rate': self.conf.router_ttl_invalid_max_rate,
                     'table': const.L3_LOOKUP_TABLE})
                return

            e_pkt = pkt.get_protocol(ethernet.ethernet)
            router_port_ip = self.router_port_rarp_cache.get(e_pkt.dst)
            if router_port_ip:
                icmp_ttl_pkt = icmp_error_generator.generate(
                    icmp.ICMP_TIME_EXCEEDED, icmp.ICMP_TTL_EXPIRED_CODE,
                    msg.data, router_port_ip, pkt)
                in_port = msg.match.get('in_port')
                self.send_packet(in_port, icmp_ttl_pkt)
            else:
                LOG.warning(_LW("The invalid TTL packet's destination mac %s "
                                "can't be recognized."), e_pkt.dst)
            return

        pkt_ip = pkt.get_protocol(ipv4.ipv4) or pkt.get_protocol(ipv6.ipv6)
        if pkt_ip is None:
            LOG.error(_LE("Received Non IP Packet"))
            return
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        if pkt_ip.dst in self.router_port_rarp_cache.values():
            # The packet's IP destination is router interface.
            # Response icmp echo request.
            # TODO(xiaohhui or lihi): support icmpv6
            if pkt_ip.proto == in_proto.IPPROTO_ICMP:
                router_unique_key = msg.match.get('reg5')
                self._install_icmp_responder(pkt_ip.dst,
                                             router_unique_key,
                                             msg)
                return

            # Response icmp unreachable to udp or tcp.
            if self.port_icmp_unreach_respond_rate_limit():
                LOG.warning(
                    _LW("Get more than %(rate)s packets to router port "
                        "per second at table %(table)s"),
                    {'rate': self.conf.router_port_unreach_max_rate,
                     'table': const.L3_LOOKUP_TABLE})
                return

            tcp_pkt = pkt.get_protocol(tcp.tcp)
            udp_pkt = pkt.get_protocol(udp.udp)
            if tcp_pkt or udp_pkt:
                icmp_dst_unreach = icmp_error_generator.generate(
                    icmp.ICMP_DEST_UNREACH, icmp.ICMP_PORT_UNREACH_CODE,
                    msg.data, pkt=pkt)
                in_port = msg.match.get('in_port')
                self.send_packet(in_port, icmp_dst_unreach)

            # Silently drop packet of other protocol.
            return

        # Normal path for a learn routing device.
        network_id = msg.match.get('metadata')
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
                dst_ports = self.db_store.get_ports_by_network_id(
                    router_port.get_lswitch_id())
                for out_port in dst_ports:
                    if out_port.get_ip() == pkt_ip.dst:
                        self._install_l3_flow(router_port,
                                              out_port, msg,
                                              network_id)
                        return

    def _install_icmp_responder(self, dst_ip, router_unique_key, msg):
        icmp_responder.ICMPResponder(
            self, dst_ip, router_unique_key).add(
                buffer_id=msg.buffer_id,
                idle_timeout=self.idle_timeout,
                hard_timeout=self.hard_timeout)

    def _install_l3_flow(self, dst_router_port, dst_port, msg,
                         src_network_id):
        reg7 = dst_port.get_unique_key()
        dst_ip = dst_port.get_ip()
        src_mac = dst_router_port.get_mac()
        dst_mac = dst_port.get_mac()
        dst_network_id = dst_port.get_external_value('local_network_id')

        parser = self.parser
        ofproto = self.ofproto

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
        actions.append(parser.OFPActionSetField(metadata=dst_network_id))
        actions.append(parser.OFPActionSetField(eth_src=src_mac))
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        actions.append(parser.OFPActionSetField(reg7=reg7))
        action_inst = parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]

        # Since we are using buffer, set buffer id to make the new OpenFlow
        # rule carry on handling original packet.
        self.mod_flow(
            cookie=dst_router_port.get_unique_key(),
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match,
            buffer_id=msg.buffer_id,
            idle_timeout=self.idle_timeout,
            hard_timeout=self.hard_timeout)

    def _add_new_router_port(self, router, router_port):
        LOG.info(_LI("Adding new logical router interface = %s"),
                 router_port)
        local_network_id = self.db_store.get_unique_key_by_id(
            models.LogicalSwitch.table_name, router_port.get_lswitch_id())
        parser = self.parser
        ofproto = self.ofproto

        router_unique_key = router.get_unique_key()
        mac = router_port.get_mac()
        tunnel_key = router_port.get_unique_key()
        dst_ip = router_port.get_ip()

        # Add router ARP for IPv4 Addresses
        is_ipv4 = netaddr.IPAddress(dst_ip).version == 4
        if is_ipv4:
            self.router_port_rarp_cache[mac] = dst_ip
            arp_responder.ArpResponder(
                self, local_network_id, dst_ip, mac).add()

        # If router interface is concrete, it will be in local cache.
        # This code is expected to be hit when refresh local data.
        lport = self.db_store.get_port(router_port.get_id())
        if lport:
            self._add_concrete_router_interface(router, lport)

        # add dst_mac=gw_mac l2 goto l3 flow
        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = [parser.OFPActionSetField(reg5=router_unique_key)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.L3_LOOKUP_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
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
                                                    port.get_unique_key())

                # From all the other interfaces to this new interface
                router_port_net_id = self.db_store.get_unique_key_by_id(
                    models.LogicalSwitch.table_name, port.get_lswitch_id())
                self._add_subnet_send_to_controller(
                    router_port_net_id,
                    router_port.get_cidr_network(),
                    router_port.get_cidr_netmask(),
                    tunnel_key)

    def _add_subnet_send_to_controller(self, network_id, dst_network,
                                       dst_netmask, dst_router_tunnel_key):
        parser = self.parser
        ofproto = self.ofproto

        if netaddr.IPAddress(dst_network).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=(dst_network, dst_netmask))
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=(dst_network, dst_netmask))

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ROUTER_PORT_BUFFER_ID)]
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            cookie=dst_router_tunnel_key,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _delete_router_port(self, router, router_port):
        LOG.info(_LI("Removing logical router interface = %s"),
                 router_port)
        local_network_id = self.db_store.get_unique_key_by_id(
            models.LogicalSwitch.table_name, router_port.get_lswitch_id())
        parser = self.parser
        ofproto = self.ofproto
        router_unique_key = router.get_unique_key()
        tunnel_key = router_port.get_unique_key()
        ip = router_port.get_ip()
        mac = router_port.get_mac()

        if netaddr.IPAddress(ip).version == 4:
            self.router_port_rarp_cache.pop(mac, None)
            arp_responder.ArpResponder(
                self, local_network_id, ip).remove()

        # Delete rule for packets whose destination is router interface.
        # The rule might not exist, but deleting it anyway will work well.
        match = self._get_router_interface_match(router_unique_key, ip)
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Delete the rules for the packets whose source is from
        # the subnet of the router port.
        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Delete the rules for the packets whose destination is to
        # the subnet of the router port.
        match = parser.OFPMatch()
        cookie = tunnel_key
        self.mod_flow(
            cookie=cookie,
            cookie_mask=cookie,
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _get_router_interface_match(self, router_unique_key, rif_ip):
        if netaddr.IPAddress(rif_ip).version == 4:
            return self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                        reg5=router_unique_key,
                                        ipv4_dst=rif_ip)

        return self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    reg5=router_unique_key,
                                    ipv6_dst=rif_ip)

    def _add_concrete_router_interface(self, router, lport):
        router_unique_key = router.get_unique_key()
        port_unique_key = lport.get_unique_key()
        match = self._get_router_interface_match(router_unique_key,
                                                 lport.get_ip())
        actions = [self.parser.OFPActionSetField(reg7=port_unique_key)]
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = self.parser.OFPInstructionGotoTable(
            const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def add_local_port(self, lport):
        LOG.debug('add local port: %s', lport)
        self._add_port(lport)

    def add_remote_port(self, lport):
        LOG.debug('add remote port: %s', lport)
        self._add_port(lport)

    def _add_port(self, lport):
        if lport.get_device_owner() != common_const.DEVICE_OWNER_ROUTER_INTF:
            return

        # The router interace is concrete, direct the packets to the real
        # port of router interface. This code is expected to be hit when
        # router port is firstly created and selective topology is used.
        router = self.db_store.get_router(lport.get_device_id())
        if router:
            self._add_concrete_router_interface(router, lport)
