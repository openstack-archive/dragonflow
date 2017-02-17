# Copyright (c) 2017 Huawei Tech. Co., Ltd. .
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
from ryu.lib import mac as ryu_mac_lib
from ryu.lib.packet import ethernet
from ryu.lib.packet import icmp
from ryu.lib.packet import packet
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
from ryu.ofproto import ether

from dragonflow._i18n import _LI, _LW
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import icmp_error_generator
from dragonflow.controller.common import icmp_responder
from dragonflow.db import models

LOG = log.getLogger(__name__)


class L3AppMixin(object):

    def __init__(self, *args, **kwargs):
        super(L3AppMixin, self).__init__()
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

    def router_function_packet_in_handler(self, msg):
        """React to packet as what a normal router will do.

        TTL invalid and router port response will be handled in this method.
        Return True if the packet is handled, so there is no need for further
        handle.
        """

        if msg.reason == self.ofproto.OFPR_INVALID_TTL:
            LOG.debug("Get an invalid TTL packet at table %s",
                      const.L3_LOOKUP_TABLE)
            if self.ttl_invalid_handler_rate_limit():
                LOG.warning(
                    _LW("Get more than %(rate)s TTL invalid "
                        "packets per second at table %(table)s"),
                    {'rate': self.conf.router_ttl_invalid_max_rate,
                     'table': const.L3_LOOKUP_TABLE})
                return True

            pkt = packet.Packet(msg.data)
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
            return True

        if msg.match.get('reg7'):
            # If the destination is router interface, the unique key of router
            # interface will be set to reg7 before sending to local controller.
            # Code will hit here only when the router interface is not
            # concrete.
            if self.port_icmp_unreach_respond_rate_limit():
                LOG.warning(
                    _LW("Get more than %(rate)s packets to router port "
                        "per second at table %(table)s"),
                    {'rate': self.conf.router_port_unreach_max_rate,
                     'table': const.L3_LOOKUP_TABLE})
                return True

            # Response icmp unreachable to udp or tcp.
            pkt = packet.Packet(msg.data)
            tcp_pkt = pkt.get_protocol(tcp.tcp)
            udp_pkt = pkt.get_protocol(udp.udp)
            if tcp_pkt or udp_pkt:
                icmp_dst_unreach = icmp_error_generator.generate(
                    icmp.ICMP_DEST_UNREACH, icmp.ICMP_PORT_UNREACH_CODE,
                    msg.data, pkt=pkt)
                in_port = msg.match.get('in_port')
                self.send_packet(in_port, icmp_dst_unreach)

            # Silently drop packet of other protocol.
            return True

        # No match in previous code.
        return False

    def router_updated(self, router, original_router):
        if not original_router:
            LOG.info(_LI("Logical Router created = %s"), router)
            self._add_new_lrouter(router)
            return

        LOG.info(_LI("Logical router updated = %s"), router)
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
            self._delete_router_port(old_port)

    def _add_new_lrouter(self, lrouter):
        for new_port in lrouter.get_ports():
            self._add_new_router_port(lrouter, new_port)

    def _get_router_interface_match(self, router_unique_key, rif_ip):
        if netaddr.IPAddress(rif_ip).version == 4:
            return self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                        reg5=router_unique_key,
                                        ipv4_dst=rif_ip)

        return self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    reg5=router_unique_key,
                                    ipv6_dst=rif_ip)

    def _get_router_route_match(self, router_unique_key,
                                dst_network, dst_netmask):
        parser = self.parser

        if netaddr.IPAddress(dst_network).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    reg5=router_unique_key,
                                    ipv4_dst=(dst_network, dst_netmask))
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    reg5=router_unique_key,
                                    ipv6_dst=(dst_network, dst_netmask))

        return match

    def _add_new_router_port(self, router, router_port):
        LOG.info(_LI("Adding new logical router interface = %s"),
                 router_port)
        local_network_id = self.db_store.get_unique_key_by_id(
            models.LogicalSwitch.table_name, router_port.get_lswitch_id())
        parser = self.parser
        ofproto = self.ofproto

        mac = router_port.get_mac()
        router_unique_key = router.get_unique_key()
        tunnel_key = router_port.get_unique_key()
        dst_ip = router_port.get_ip()
        is_ipv4 = netaddr.IPAddress(dst_ip).version == 4

        # Add rule for making packets go from L2_LOOKUP_TABLE
        # to L3_LOOKUP_TABLE
        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(ryu_mac_lib.haddr_to_bin(mac))
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

        # Add router ARP & ICMP responder for IPv4 Addresses
        if is_ipv4:
            self.router_port_rarp_cache[mac] = dst_ip
            arp_responder.ArpResponder(self,
                                       local_network_id,
                                       dst_ip, mac).add()
            icmp_responder.ICMPResponder(self,
                                         dst_ip,
                                         router_key=router_unique_key).add()

        # If router interface is not concrete, send to local controller. local
        # controller will create icmp unreachable mesage. A virtual router
        # interface will not be in local cache, as it doesn't have chassis
        # information.
        lport = self.db_store.get_port(router_port.get_id())
        if not lport:
            match = self._get_router_interface_match(router_unique_key, dst_ip)
            actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                              ofproto.OFPCML_NO_BUFFER)]
            action_inst = parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)
            self.mod_flow(
                inst=[action_inst],
                table_id=const.L3_LOOKUP_TABLE,
                priority=const.PRIORITY_HIGH,
                match=match)
        else:
            self._add_concrete_router_interface(lport, router=router)

        # Add rule for routing packets to subnet of this router port
        match = self._get_router_route_match(router_unique_key,
                                             router_port.get_cidr_network(),
                                             router_port.get_cidr_netmask())
        self._add_subnet_send_to_route(match, local_network_id, router_port)

        # Fall through to sNAT
        self._add_subnet_send_to_snat(local_network_id, mac, tunnel_key)

    def _delete_router_port(self, router, router_port):
        LOG.info(_LI("Removing logical router interface = %s"),
                 router_port)
        local_network_id = self.db_store.get_unique_key_by_id(
            models.LogicalSwitch.table_name, router_port.get_lswitch_id())

        parser = self.parser
        ofproto = self.ofproto
        router_unique_key = router.get_unique_key()
        ip = router_port.get_ip()
        mac = router_port.get_mac()

        # Delete rule for making packets go from L2_LOOKUP_TABLE
        # to L3_LOOKUP_TABLE
        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(ryu_mac_lib.haddr_to_bin(mac))
        self.mod_flow(
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Delete ARP & ICMP responder for router interface
        if netaddr.IPAddress(ip).version == 4:
            self.router_port_rarp_cache.pop(mac, None)

            arp_responder.ArpResponder(self, local_network_id, ip).remove()
            icmp_responder.ICMPResponder(self, ip,
                                         router_key=router_unique_key).remove()

        # Delete rule for packets whose destination is router interface.
        match = self._get_router_interface_match(router_unique_key, ip)
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Delete rule for routing packets to subnet of this router port
        match = self._get_router_route_match(router_unique_key,
                                             router_port.get_cidr_network(),
                                             router_port.get_cidr_netmask())
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Delete rule for SNAT
        self._delete_subnet_send_to_snat(local_network_id, mac)

    def _add_subnet_send_to_snat(self, network_id, mac, tunnel_key):
        ofproto = self.ofproto
        parser = self.parser
        match = parser.OFPMatch(metadata=network_id, eth_dst=mac)
        actions = [parser.OFPActionSetField(reg7=tunnel_key)]
        inst = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
            parser.OFPInstructionGotoTable(const.EGRESS_TABLE),
        ]
        self.mod_flow(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_LOW,
            match=match)

    def _delete_subnet_send_to_snat(self, network_id, mac):
        ofproto = self.ofproto
        parser = self.parser
        match = parser.OFPMatch(metadata=network_id, eth_dst=mac)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_LOW,
            match=match)

    def add_local_port(self, lport):
        LOG.debug('add local port: %s', lport)
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_concrete_router_interface(lport)
        else:
            self._add_port(lport)

    def add_remote_port(self, lport):
        LOG.debug('add remote port: %s', lport)
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_concrete_router_interface(lport)
        else:
            self._add_port(lport)

    def _add_concrete_router_interface(self, lport, router=None):
        # The router interace is concrete, direct the packets to the real
        # port of router interface. The flow here will overwrite
        # the flow that packet-in the packets to local controller.
        router = router or self.db_store.get_router(lport.get_device_id())
        if not router:
            return

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

    def _add_port(self, lport):
        """Add port which is not a router interface."""
        # Do nothing by default.
        pass

    def remove_local_port(self, lport):
        LOG.debug('remove local port:%s', lport)
        # Let the router update process to delete flows for concrete
        # router port, if there is any.
        if lport.get_device_owner() != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._remove_port(lport)

    def remove_remote_port(self, lport):
        LOG.debug('remove remote port:%s', lport)
        # Let the router update process to delete flows for concrete
        # router port, if there is any.
        if lport.get_device_owner() != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._remove_port(lport)

    def _remove_port(self, lport):
        """Remove port which is not a router interface."""
        # Do nothing by default.
        pass
