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
from ryu.ofproto import ether

from dragonflow._i18n import _LI
from dragonflow.common import exceptions
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import icmp_responder
from dragonflow.controller import df_base_app

ROUTE_TO_ADD = 'route_to_add'
ROUTE_ADDED = 'route_added'
LOG = log.getLogger(__name__)


class L3ProactiveApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(L3ProactiveApp, self).__init__(*args, **kwargs)
        self.route_cache = {}

    def switch_features_handler(self, ev):
        self.add_flow_go_to_table(self.get_datapath(),
                                  const.L3_LOOKUP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.EGRESS_TABLE)

    def add_router_port(self, router, router_port, local_network_id):
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        mac = router_port.get_mac()
        tunnel_key = router_port.get_tunnel_key()
        dst_ip = router_port.get_ip()

        # Add router ARP & ICMP responder for IPv4 Addresses
        is_ipv4 = netaddr.IPAddress(dst_ip).version == 4
        if is_ipv4:
            arp_responder.ArpResponder(datapath,
                                       local_network_id,
                                       dst_ip, mac).add()
            icmp_responder.ICMPResponder(datapath, dst_ip, mac).add()

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

        # Add router ip match go to output table
        self._install_flow_send_to_output_table(local_network_id,
                                                tunnel_key,
                                                dst_ip)

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

        # Match all possible routeable traffic and send to proactive routing
        for port in router.get_ports():
            if port.get_id() != router_port.get_id():

                port_net_id = self.db_store.get_network_id(
                    port.get_lswitch_id(),
                )

                # From this router interface to all other interfaces
                self._add_subnet_send_to_proactive_routing(
                    local_network_id,
                    port.get_cidr_network(),
                    port.get_cidr_netmask(),
                    port.get_tunnel_key(),
                    port_net_id,
                    port.get_mac())

                # From all the other interfaces to this new interface
                self._add_subnet_send_to_proactive_routing(
                    port_net_id,
                    router_port.get_cidr_network(),
                    router_port.get_cidr_netmask(),
                    tunnel_key,
                    local_network_id,
                    router_port.get_mac())

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
                    self._add_to_route_cache(ROUTE_ADDED, router, route_dict)
                    self._del_from_route_cache(ROUTE_TO_ADD, router,
                                               route_dict)

    def _reprocess_to_del_route(self, topic, port_ip):
        LOG.debug('reprocess to del routes again')
        for router in self.db_store.get_routers(topic):
            router_id = router.get_id()
            cached_routes = self.route_cache.get(router_id, None)
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

    def _add_router_route(self, router, route):

        datapath = self.get_datapath()
        ofproto = self.get_datapath().ofproto
        parser = datapath.ofproto_parser

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
        tunnel_key = nexthop_port.get_tunnel_key()
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

        self.mod_flow(
            self.get_datapath(),
            cookie=tunnel_key,
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

    def add_router_route(self, router, route):
        LOG.info(_LI('Add extra route %(route)s for router %(router)s') %
                 {'route': route, 'router': str(router)})

        added = self._add_router_route(router, route)
        if added:
            self._add_to_route_cache(ROUTE_ADDED, router, route)
        else:
            self._add_to_route_cache(ROUTE_TO_ADD, router, route)

    def _remove_router_route(self, router, route):
        datapath = self.get_datapath()
        ofproto = self.get_datapath().ofproto
        parser = datapath.ofproto_parser

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
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        return

    def remove_router_route(self, router, route):
        LOG.debug('Delete extra route %(route)s from router %(router)s' %
                 {'route': route, 'router': str(router)})

        self._remove_router_route(router, route)
        self._del_from_route_cache(ROUTE_ADDED, router.get_id(), route)
        self._del_from_route_cache(ROUTE_TO_ADD, router.get_id(), route)

    def _install_flow_send_to_output_table(self, network_id,
                                           tunnel_key, dst_ip):
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
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _add_subnet_send_to_proactive_routing(self, network_id, dst_network,
                                              dst_netmask,
                                              dst_router_tunnel_key,
                                              dst_network_id,
                                              dst_router_port_mac):
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

        actions = []
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(metadata=dst_network_id))
        actions.append(parser.OFPActionSetField(eth_src=dst_router_port_mac))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.L3_PROACTIVE_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=dst_router_tunnel_key,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def remove_router_port(self, router_port, local_network_id):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        tunnel_key = router_port.get_tunnel_key()
        ip = router_port.get_ip()
        mac = router_port.get_mac()

        if netaddr.IPAddress(ip).version == 4:
            arp_responder.ArpResponder(self.get_datapath(),
                                       local_network_id, ip).remove()
            icmp_responder.ICMPResponder(self.get_datapath(), ip, mac).remove()

        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
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
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Remove router port ip proactive flow
        if netaddr.IPAddress(router_port.get_ip()).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=local_network_id,
                                    ipv4_dst=router_port.get_ip())
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=local_network_id,
                                    ipv6_dst=router_port.get_ip())
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def add_local_port(self, lport):
        LOG.debug('add local port: %s', lport)
        self._add_port(lport)

    def add_remote_port(self, lport):
        LOG.debug('add remote port: %s', lport)
        self._add_port(lport)

    def _add_port(self, lport):
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            return

        dst_ip = lport.get_ip()
        dst_mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        tunnel_key = lport.get_tunnel_key()

        self._add_port_process(dst_ip, dst_mac, network_id, tunnel_key)
        self._reprocess_to_add_route(lport.get_topic(), dst_ip)

    def _add_port_process(self, dst_ip, dst_mac, network_id, tunnel_key,
                          priority=const.PRIORITY_HIGH):
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
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def remove_local_port(self, lport):
        LOG.debug('remove local port:%s', str(lport))
        self._remove_port(lport)

    def remove_remote_port(self, lport):
        LOG.debug('remove remote port:%s', str(lport))
        self._remove_port(lport)

    def _remove_port(self, lport):
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            return
        dst_ip = lport.get_ip()
        network_id = lport.get_external_value('local_network_id')

        self._remove_port_process(dst_ip, network_id)
        self._reprocess_to_del_route(lport.get_topic(), dst_ip)

    def _remove_port_process(self, dst_ip, network_id,
                             priority=const.PRIORITY_HIGH):
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

        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)
