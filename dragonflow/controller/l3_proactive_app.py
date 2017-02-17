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
from ryu.ofproto import ether

from dragonflow._i18n import _LI
from dragonflow.common import exceptions
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from dragonflow.controller import l3_app_base

ROUTE_TO_ADD = 'route_to_add'
ROUTE_ADDED = 'route_added'
COOKIE_NAME = 'tunnel_key'
LOG = log.getLogger(__name__)


class L3ProactiveApp(df_base_app.DFlowApp, l3_app_base.L3AppMixin):
    def __init__(self, *args, **kwargs):
        super(L3ProactiveApp, self).__init__(*args, **kwargs)
        self.route_cache = {}
        self.register_local_cookie_bits(COOKIE_NAME, 24)

    def packet_in_handler(self, event):
        msg = event.msg
        self.router_function_packet_in_handler(msg)

    def router_updated(self, router, original_router):
        super(L3ProactiveApp, self).router_updated(router, original_router)
        if original_router:
            # NOTE(xiaohhui): extra route is only implemented in L3ProactiveApp
            self._update_router_attributes(original_router, router)

    def _update_router_attributes(self, old_router, new_router):
        old_routes = old_router.get_routes()
        new_routes = new_router.get_routes()
        for new_route in new_routes:
            if new_route not in old_routes:
                self._add_router_route(new_router, new_route)
            else:
                old_routes.remove(new_route)
        for old_route in old_routes:
            self._delete_router_route(new_router, old_route)

    def _add_new_lrouter(self, lrouter):
        super(L3ProactiveApp, self)._add_new_lrouter(lrouter)
        for route in lrouter.get_routes():
            self._add_router_route(lrouter, route)

    def _get_port(self, ip, lswitch_id, topic):
        ports = self.db_store.get_ports(topic)
        for port in ports:
            if port.get_ip() == ip and port.get_lswitch_id() == lswitch_id:
                return port

    def _get_gateway_port_by_ip(self, router, ip):
        for port in router.get_ports():
            network = netaddr.IPNetwork(port.get_network())
            if netaddr.IPAddress(ip) in network:
                return port

        raise exceptions.DBStoreRecordNotFound(
            record='RouterPort(router=%s, ip=%s)' % (router.get_name(), ip))

    # route cache got following structure
    # {router: {ROUTE_ADDED: set(route), ROUTE_TO_ADD: set(route)}
    def _add_to_route_cache(self, key, router_id, route):
        cached_routes = self.route_cache.get(router_id)
        if cached_routes is None:
            cached_routes = {ROUTE_ADDED: set(), ROUTE_TO_ADD: set()}
            self.route_cache[router_id] = cached_routes
        routes = cached_routes.get(key)
        routes.add((route.get('destination'), route.get('nexthop')))

    def _del_from_route_cache(self, key, router_id, route):
        cached_routes = self.route_cache.get(router_id)
        if cached_routes is None:
            return
        routes = cached_routes.get(key)
        routes.discard(
            (route.get('destination'), route.get('nexthop')))

    def _reprocess_to_add_route(self, topic, port_ip):
        LOG.debug('reprocess to add routes again')
        for router in self.db_store.get_routers(topic):
            router_id = router.get_id()
            cached_routes = self.route_cache.get(router_id)
            if cached_routes is None:
                continue
            routes_to_add = cached_routes.get(ROUTE_TO_ADD)
            LOG.debug('routes to add: %s', routes_to_add)
            for route in routes_to_add:
                if port_ip != route[1]:
                    continue
                route_dict = dict(zip(['destination', 'nexthop'], route))
                added = self._add_route_route(router, route_dict)
                if added:
                    self._add_to_route_cache(ROUTE_ADDED, router_id,
                                             route_dict)
                    self._del_from_route_cache(ROUTE_TO_ADD, router_id,
                                               route_dict)

    def _reprocess_to_del_route(self, topic, port_ip):
        LOG.debug('reprocess to del routes again')
        for router in self.db_store.get_routers(topic):
            router_id = router.get_id()
            cached_routes = self.route_cache.get(router_id)
            if cached_routes is None:
                continue
            routes_added = cached_routes.get(ROUTE_ADDED)
            for route in routes_added:
                if port_ip != route[1]:
                    continue
                route_dict = dict(zip(['destination', 'nexthop'], route))
                self._remove_router_route(router, route_dict)
                self._del_from_route_cache(ROUTE_ADDED, router_id, route_dict)
                self._add_to_route_cache(ROUTE_TO_ADD, router_id, route_dict)

    def _add_route_process(self, router, route):
        ofproto = self.ofproto
        parser = self.parser

        destination = route.get('destination')
        destination = netaddr.IPNetwork(destination)
        nexthop = route.get('nexthop')
        router_if_port = self._get_gateway_port_by_ip(router, nexthop)
        nexthop_port = self._get_port(
            nexthop, router_if_port.get_lswitch_id(), router.get_topic())
        if nexthop_port is None:
            LOG.info(_LI('nexthop port does not exist'))
            return False

        # Install openflow entry for the route
        # Match: ip, metadata=network_id, nw_src=src_network/mask,
        #        nw_dst=dst_network/mask,
        #  Actions:ttl-1, mod_dl_dst=next_hop_mac, load_reg7=next_hop_port_key,
        #  goto: egress_table
        dst_mac = nexthop_port.get_mac()
        tunnel_key = nexthop_port.get_unique_key()
        match = self._generate_l3_match(parser,
                                        destination,
                                        nexthop_port,
                                        router_if_port)

        actions = [
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(eth_dst=dst_mac),
            parser.OFPActionSetField(reg7=tunnel_key),
        ]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)

        inst = [action_inst, goto_inst]

        cookie, cookie_mask = self.get_local_cookie(COOKIE_NAME, tunnel_key)
        self.mod_flow(
            cookie=cookie,
            cookie_mask=cookie_mask,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match)

        return True

    def _generate_l3_match(self, parser, destination, nexthop_port,
                           router_if_port):
        router_if_mac = router_if_port.get_mac()
        network_id = nexthop_port.get_external_value('local_network_id')
        src_network = router_if_port.get_cidr_network()
        src_netmask = router_if_port.get_cidr_netmask()
        dst_network = destination.network
        dst_netmask = destination.netmask
        if destination.version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    eth_dst=router_if_mac,
                                    ipv4_src=(src_network, src_netmask),
                                    ipv4_dst=(dst_network, dst_netmask))
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    eth_dst=router_if_mac,
                                    ipv6_src=(src_network, src_netmask),
                                    ipv6_dst=(dst_network, dst_netmask))
        return match

    def _add_router_route(self, router, route):
        LOG.info(_LI('Add extra route %(route)s for router %(router)s'),
                 {'route': route, 'router': str(router)})

        router_id = router.get_id()
        added = self._add_route_process(router, route)
        if added:
            self._add_to_route_cache(ROUTE_ADDED, router_id, route)
        else:
            self._add_to_route_cache(ROUTE_TO_ADD, router_id, route)

    def _delete_route_process(self, router, route):
        ofproto = self.ofproto
        parser = self.parser

        destination = route.get('destination')
        destination = netaddr.IPNetwork(destination)
        nexthop = route.get('nexthop')
        router_if_port = self._get_gateway_port_by_ip(router, nexthop)
        nexthop_port = self._get_port(
            nexthop, router_if_port.get_lswitch_id(), router.get_topic())
        if nexthop_port is None:
            LOG.info(_LI('nexthop does not exist'))
            return

        # remove openflow entry for the route
        # Match: ip, metadata=network_id, nw_src=src_network/mask,
        #        nw_dst=dst_network/mask,
        match = self._generate_l3_match(parser,
                                        destination,
                                        nexthop_port,
                                        router_if_port)

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match)

        return

    def _delete_router_route(self, router, route):
        LOG.debug('Delete extra route %(route)s from router %(router)s',
                  {'route': route, 'router': router})

        self._delete_route_process(router, route)
        self._del_from_route_cache(ROUTE_ADDED, router.get_id(), route)
        self._del_from_route_cache(ROUTE_TO_ADD, router.get_id(), route)

    def _add_subnet_send_to_route(self, match, local_network_id, router_port):
        self._add_subnet_send_to_proactive_routing(match, local_network_id,
                                                   router_port.get_mac())

    def _add_subnet_send_to_proactive_routing(self, match, dst_network_id,
                                              dst_router_port_mac):
        parser = self.parser
        ofproto = self.ofproto

        actions = []
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(metadata=dst_network_id))
        actions.append(parser.OFPActionSetField(eth_src=dst_router_port_mac))
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.L3_PROACTIVE_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]

        self.mod_flow(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _add_port(self, lport):
        """Add port which is not a router interface."""
        dst_ip = lport.get_ip()
        dst_mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        tunnel_key = lport.get_unique_key()

        self._add_port_process(dst_ip, dst_mac, network_id, tunnel_key)
        self._reprocess_to_add_route(lport.get_topic(), dst_ip)

    def _add_port_process(self, dst_ip, dst_mac, network_id, tunnel_key,
                          priority=const.PRIORITY_HIGH):
        parser = self.parser
        ofproto = self.ofproto

        if netaddr.IPAddress(dst_ip).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=dst_ip)

        actions = []
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _remove_port(self, lport):
        """Remove port which is not a router interface."""
        dst_ip = lport.get_ip()
        network_id = lport.get_external_value('local_network_id')

        self._remove_port_process(dst_ip, network_id)
        self._reprocess_to_del_route(lport.get_topic(), dst_ip)

    def _remove_port_process(self, dst_ip, network_id,
                             priority=const.PRIORITY_HIGH):
        parser = self.parser
        ofproto = self.ofproto

        if netaddr.IPAddress(dst_ip).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=dst_ip)

        self.mod_flow(
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)
