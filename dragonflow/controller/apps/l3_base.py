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

import copy

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

from dragonflow.common import exceptions
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import icmp_error_generator
from dragonflow.controller.common import icmp_responder
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import host_route
from dragonflow.db.models import l2
from dragonflow.db.models import l3


ROUTE_TO_ADD = 'route_to_add'
ROUTE_ADDED = 'route_added'
LOG = log.getLogger(__name__)


class L3AppMixin(object):

    def __init__(self, *args, **kwargs):
        super(L3AppMixin, self).__init__()
        self.route_cache = {}

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
        self.route_cache.clear()

    def _handle_ttl_expired(self, msg):
        if self.ttl_invalid_handler_rate_limit():
            LOG.warning("Get more than %(rate)s TTL invalid packets per "
                        "second at table %(table)s",
                        {'rate': self.conf.router_ttl_invalid_max_rate,
                         'table': const.L3_LOOKUP_TABLE})
            return

        LOG.debug("Get an invalid TTL packet at table %s",
                  const.L3_LOOKUP_TABLE)

        pkt = packet.Packet(msg.data)
        e_pkt = pkt.get_protocol(ethernet.ethernet)
        router_key = msg.match.get('reg5')
        lrouter = self.db_store.get_one(
            l3.LogicalRouter(unique_key=router_key),
            index=l3.LogicalRouter.get_index('unique_key'),
        )
        router_port_ip = None
        for port in lrouter.ports:
            if port.lswitch.unique_key == msg.match.get('metadata'):
                router_port_ip = port.network.ip
                break

        if router_port_ip:
            icmp_ttl_pkt = icmp_error_generator.generate(
                icmp.ICMP_TIME_EXCEEDED, icmp.ICMP_TTL_EXPIRED_CODE,
                msg.data, str(router_port_ip), pkt)
            unique_key = msg.match.get('reg6')
            self.dispatch_packet(icmp_ttl_pkt, unique_key)
        else:
            LOG.warning("The invalid TTL packet's destination mac %s "
                        "can't be recognized.", e_pkt.dst)

    def _handle_invalid_dest(self, msg):
        # If the destination is router interface, the unique key of router
        # interface will be set to reg7 before sending to local controller.
        # Code will hit here only when the router interface is not
        # concrete.
        if self.port_icmp_unreach_respond_rate_limit():
            LOG.warning(
                "Get more than %(rate)s packets to router port "
                "per second at table %(table)s",
                {'rate': self.conf.router_port_unreach_max_rate,
                 'table': const.L3_LOOKUP_TABLE})
            return

        # Response icmp unreachable to udp or tcp.
        pkt = packet.Packet(msg.data)
        tcp_pkt = pkt.get_protocol(tcp.tcp)
        udp_pkt = pkt.get_protocol(udp.udp)
        if tcp_pkt or udp_pkt:
            icmp_dst_unreach = icmp_error_generator.generate(
                icmp.ICMP_DEST_UNREACH, icmp.ICMP_PORT_UNREACH_CODE,
                msg.data, pkt=pkt)
            unique_key = msg.match.get('reg6')
            self.dispatch_packet(icmp_dst_unreach, unique_key)

    def router_function_packet_in_handler(self, msg):
        """React to packet as what a normal router will do.

        TTL invalid and router port response will be handled in this method.
        Return True if the packet is handled, so there is no need for further
        handle.
        """

        if msg.reason == self.ofproto.OFPR_INVALID_TTL:
            self._handle_ttl_expired(msg)
        elif msg.match.get('reg7'):
            self._handle_invalid_dest(msg)
        else:
            return False

        return True

    @df_base_app.register_event(l3.LogicalRouter,
                                model_constants.EVENT_CREATED)
    def router_created(self, router):
        for new_port in router.ports:
            self._add_new_router_port(router, new_port)
        for route in router.routes:
            self._add_router_extra_route(router, route)

    @df_base_app.register_event(l3.LogicalRouter,
                                model_constants.EVENT_UPDATED)
    def router_updated(self, router, original_router=None):
        self._update_router_interfaces(original_router, router)
        self._update_router_attributes(original_router, router)

    @df_base_app.register_event(l3.LogicalRouter,
                                model_constants.EVENT_DELETED)
    def router_deleted(self, router):
        for port in router.ports:
            self._delete_router_port(router, port)
        for route in router.routes:
            self._delete_router_extra_route(router, route)
        self.route_cache.pop(router.id, None)

    def _update_router_interfaces(self, old_router, new_router):
        old_ports = old_router.ports
        new_ports = new_router.ports
        for old_port in old_ports:
            if old_port not in new_ports:
                self._delete_router_port(new_router, old_port)
        for new_port in new_ports:
            if new_port not in old_ports:
                self._add_new_router_port(new_router, new_port)

    def _update_router_attributes(self, old_router, new_router):
        old_routes = old_router.routes
        new_routes = new_router.routes
        for old_route in old_routes:
            if old_route not in new_routes:
                self._delete_router_extra_route(new_router, old_route)
        for new_route in new_routes:
            if new_route not in old_routes:
                self._add_router_extra_route(new_router, new_route)

    def _get_port_by_lswitch_and_ip(self, ip, lswitch_id):
        ip_lswitch_idx = l2.LogicalPort.get_index('ip,lswitch')
        ports = self.db_store.get_all(l2.LogicalPort(lswitch=lswitch_id,
                                                     ips=[ip]),
                                      index=ip_lswitch_idx)
        return next(ports, None)

    def _get_gateway_port_by_ip(self, router, ip):
        for port in router.ports:
            if ip in port.network:
                return port

        # Code is not expected to hit here as neutron will prevent from adding
        # unreachable route.
        raise exceptions.DBStoreRecordNotFound(
            record='RouterPort(router=%s, ip=%s)' % (router.name, ip))

    def _add_router_extra_route(self, router, route):
        """Add extra route to router."""

        LOG.debug('Add extra route %(route)s to router %(router)s',
                  {'route': route, 'router': router})

        router_port = self._get_gateway_port_by_ip(router, route.nexthop)
        lport = self._get_port_by_lswitch_and_ip(route.nexthop,
                                                 router_port.lswitch.id)
        router_id = router.id
        if not lport:
            LOG.debug("lport with IP %s doesn't exist, skip adding "
                      "extra route.", route.nexthop)
            self._add_to_route_cache(ROUTE_TO_ADD, router_id, route)
            return

        self._add_extra_route_to_router(router.unique_key,
                                        router_port.mac,
                                        lport.unique_key,
                                        lport.mac, route)
        self._add_to_route_cache(ROUTE_ADDED, router_id, route)

    def _delete_router_extra_route(self, router, route):
        """Delete extra route from router."""

        LOG.debug('Delete extra route %(route)s from router %(router)s',
                  {'route': route, 'router': router})

        router_port = self._get_gateway_port_by_ip(router, route.nexthop)
        router_unique_key = router.unique_key
        router_if_mac = router_port.mac
        # Delete the openflow for extra route anyway.
        self._delete_extra_route_from_router(router_unique_key,
                                             router_if_mac, route)
        self._del_from_route_cache(ROUTE_ADDED, router.id, route)
        self._del_from_route_cache(ROUTE_TO_ADD, router.id, route)

    def _add_extra_route_to_router(self, router_unique_key, router_if_mac,
                                   lport_unique_key, lport_mac, route):
        """Add extra route to router.
        @param router_unique_key: The unique_key of router where the extra
                                  route belongs to
        @param router_if_mac: The mac address of related router port
        @param lport_unique_key: The unique_key of lport whick will act as
                                 nexthop.
        @param lport_mac: The mac address of lport which will act as nexthop
        @param route: The extra route dict
        """
        LOG.info('Add extra route %s to router', route)

        ofproto = self.ofproto
        parser = self.parser

        # Install openflow entry for extra route, only packets come from
        # the same subnet as nexthop port can use extra route.
        # Match: ip, reg5=router_unique_key, dl_dst=router_if_mac,
        #        nw_dst=destination,
        # Actions:ttl-1, mod_dl_src=router_if_mac, mod_dl_dst=lport_mac,
        #         load_reg7=next_hop_port_key,
        # goto: egress_table
        match = self._generate_extra_route_match(router_unique_key,
                                                 router_if_mac,
                                                 route.destination)

        actions = [
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(eth_src=router_if_mac),
            parser.OFPActionSetField(eth_dst=lport_mac),
            parser.OFPActionSetField(reg7=lport_unique_key),
        ]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match)

    def _delete_extra_route_from_router(self, router_unique_key,
                                        router_if_mac, route):
        """Delete extra route from router.
        @param router_unique_key: The unique_key of router where the extra
                                  route belongs to
        @param router_if_mac: The mac address of related router port
        @param route: The extra route dict
        """
        LOG.info('Delete extra route %s from router', route)

        ofproto = self.ofproto

        # Remove openflow entry for extra route
        # Match: ip, reg5=router_unique_key, dl_dst=router_if_mac,
        #        nw_dst=destination
        match = self._generate_extra_route_match(router_unique_key,
                                                 router_if_mac,
                                                 route.destination)

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match)

    def _generate_extra_route_match(self, router_unique_key, router_if_mac,
                                    destination):
        dst_network = destination.network
        dst_netmask = destination.netmask
        if destination.version == common_const.IP_VERSION_4:
            match = self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                         reg5=router_unique_key,
                                         eth_dst=router_if_mac,
                                         ipv4_dst=(dst_network, dst_netmask))
        else:
            match = self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                         reg5=router_unique_key,
                                         eth_dst=router_if_mac,
                                         ipv6_dst=(dst_network, dst_netmask))
        return match

    # route cache got following structure
    # {router: {ROUTE_ADDED: set(route), ROUTE_TO_ADD: set(route)}
    def _add_to_route_cache(self, key, router_id, route):
        cached_routes = self.route_cache.get(router_id)
        if cached_routes is None:
            cached_routes = {ROUTE_ADDED: set(), ROUTE_TO_ADD: set()}
            self.route_cache[router_id] = cached_routes
        routes = cached_routes.get(key)
        routes.add((str(route.destination), str(route.nexthop)))

    def _del_from_route_cache(self, key, router_id, route):
        cached_routes = self.route_cache.get(router_id)
        if cached_routes is None:
            return
        routes = cached_routes.get(key)
        routes.discard((str(route.destination), str(route.nexthop)))

    def _change_route_cache_status(self, router_id, from_part, to_part, route):
        """Change the status of extra route in cache of app.

        @param router_id The cache belongs to which router.
        @param from_part From which part the extra route will be moved.
        @param to_part   To which part the extra route will be moved.
        @param route     The extra route to move.
        """
        self._del_from_route_cache(from_part, router_id, route)
        self._add_to_route_cache(to_part, router_id, route)

    def _get_router_interface_match(self, router_unique_key, rif_ip):
        if netaddr.IPAddress(rif_ip).version == common_const.IP_VERSION_4:
            return self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                        reg5=router_unique_key,
                                        ipv4_dst=rif_ip)

        return self.parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    reg5=router_unique_key,
                                    ipv6_dst=rif_ip)

    def _get_router_route_match(self, router_unique_key,
                                dst_network, dst_netmask):
        parser = self.parser

        if netaddr.IPAddress(dst_network).version == common_const.IP_VERSION_4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    reg5=router_unique_key,
                                    ipv4_dst=(dst_network, dst_netmask))
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    reg5=router_unique_key,
                                    ipv6_dst=(dst_network, dst_netmask))

        return match

    def _add_new_router_port(self, router, router_port):
        LOG.info("Adding new logical router interface = %r",
                 router_port)
        local_network_id = router_port.lswitch.unique_key

        parser = self.parser
        ofproto = self.ofproto

        mac = router_port.mac
        router_unique_key = router.unique_key
        dst_ip = router_port.network.ip
        is_ipv4 = (netaddr.IPAddress(dst_ip).version ==
                   common_const.IP_VERSION_4)

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
        lport = self.db_store.get_one(l2.LogicalPort(id=router_port.id))
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
                                             router_port.network.network,
                                             router_port.network.netmask)
        self._add_subnet_send_to_route(match, local_network_id, router_port)

    def _delete_router_port(self, router, router_port):
        LOG.info("Removing logical router interface = %s",
                 router_port)
        local_network_id = router_port.lswitch.unique_key

        parser = self.parser
        ofproto = self.ofproto
        router_unique_key = router.unique_key
        ip = router_port.network.ip
        mac = router_port.mac

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
        if ip.version == common_const.IP_VERSION_4:
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
                                             router_port.network.network,
                                             router_port.network.netmask)
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_REMOTE)
    def _add_port_event_handler(self, lport):
        LOG.debug('add %(locality)s port: %(lport)s',
                  {'lport': lport,
                   'locality': 'local' if lport.is_local else 'remote'})
        if lport.device_owner == common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_concrete_router_interface(lport)
        else:
            self._add_port(lport)

    def _add_concrete_router_interface(self, lport, router=None):
        # The router interace is concrete, direct the packets to the real
        # port of router interface. The flow here will overwrite
        # the flow that packet-in the packets to local controller.
        router = router or self.db_store.get_one(
            l3.LogicalRouter(id=lport.device_id))
        if not router:
            return

        router_unique_key = router.unique_key
        port_unique_key = lport.unique_key
        match = self._get_router_interface_match(router_unique_key, lport.ip)
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

    def _get_router_by_lswitch_and_port_ip(self, lswitch_id, port_ip):
        """Find and return the logical router that lport connects to.

        @param lswitch_id: The lswitch id of lport
        @param port_ip: The ip of lport
        @return Router and the router port that is the gateway of lport
        """
        for router in self.db_store.get_all(l3.LogicalRouter):
            for port in router.ports:
                if (lswitch_id == port.lswitch.id and
                        netaddr.IPAddress(port_ip) in port.network):
                    return router, port
        return None, None

    def _reprocess_to_add_route(self, lport):
        """Add extra routes for lport.

        @param lport: The lport related to extra routes.
        """
        LOG.debug("Reprocess to add extra routes that use lport %s "
                  "as nexthop", lport)
        lswitch_id = lport.lswitch.id
        port_ip = lport.ip
        router, router_if = self._get_router_by_lswitch_and_port_ip(
            lswitch_id, port_ip)
        if not router:
            LOG.debug("No router for lport %s, skip adding extra route",
                      lport)
            return

        router_id = router.id
        cached_routes = self.route_cache.get(router_id)
        if not cached_routes or not cached_routes.get(ROUTE_TO_ADD):
            LOG.debug("No extra routes need to be processed for logical "
                      "router %s", router)
            return

        # Make a copy here, or else _change_route_cache_status will delete
        # elements in routes inside the iteration.
        routes = copy.deepcopy(cached_routes.get(ROUTE_TO_ADD))
        for route in routes:
            if str(port_ip) != route[1]:
                continue
            route = host_route.HostRoute(destination=route[0],
                                         nexthop=route[1])
            self._add_extra_route_to_router(router.unique_key,
                                            router_if.mac,
                                            lport.unique_key,
                                            lport.mac,
                                            route)
            self._change_route_cache_status(router_id,
                                            from_part=ROUTE_TO_ADD,
                                            to_part=ROUTE_ADDED,
                                            route=route)

    def _reprocess_to_delete_route(self, lport):
        """Delete extra routes for lport.

        @param lport: The lport related to extra routes.
        """
        LOG.debug("Reprocess to delete extra routes that use lport %s "
                  "as nexthop", lport)
        lswitch_id = lport.lswitch.id
        port_ip = lport.ip
        router, router_if = self._get_router_by_lswitch_and_port_ip(
            lswitch_id, port_ip)
        if not router:
            LOG.debug("No router for lport %s, skip adding extra route",
                      lport)
            return

        router_id = router.id
        cached_routes = self.route_cache.get(router_id)
        if not cached_routes or not cached_routes.get(ROUTE_ADDED):
            LOG.debug("No extra routes need to be processed for logical "
                      "router %s", router)
            return

        # Make a copy here, or else _change_route_cache_status will delete
        # elements in routes inside the iteration.
        routes = copy.deepcopy(cached_routes.get(ROUTE_ADDED))
        for route in routes:
            if str(port_ip) != route[1]:
                continue
            route = host_route.HostRoute(destination=route[0],
                                         nexthop=route[1])
            self._delete_extra_route_from_router(router.unique_key,
                                                 router_if.mac,
                                                 route)
            self._change_route_cache_status(router_id,
                                            from_part=ROUTE_ADDED,
                                            to_part=ROUTE_TO_ADD,
                                            route=route)

    def _add_port(self, lport):
        """Add port which is not a router interface."""
        self._reprocess_to_add_route(lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_REMOTE)
    def _remove_port_event_handler(self, lport):
        LOG.debug('remove %(locality)s port: %(lport)s',
                  {'lport': lport,
                   'locality': 'local' if lport.is_local else 'remote'})
        # Let the router update process to delete flows for concrete
        # router port, if there is any.
        if lport.device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._remove_port(lport)

    def _remove_port(self, lport):
        """Remove port which is not a router interface."""
        self._reprocess_to_delete_route(lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_UPDATED)
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_REMOTE_UPDATED)
    def _update_port_event_handler(self, lport, orig_lport):
        LOG.debug('remove %(locality)s port: %(lport)s',
                  {'lport': lport,
                   'locality': 'local' if lport.is_local else 'remote'})

        if lport.device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._update_port(lport, orig_lport)

    def _update_port(self, lport, orig_lport):
        pass
