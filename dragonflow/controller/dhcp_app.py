# Copyright (c) 2015 Huawei Tech. Co., Ltd. .
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

import collections
import copy
import math
import struct

import netaddr
from neutron.conf import common as common_config
from neutron_lib import constants as n_const
from oslo_log import log
from ryu.lib import addrconv
from ryu.lib.packet import dhcp
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet as ryu_packet
from ryu.lib.packet import udp
from ryu.ofproto import ether

from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import host_route
from dragonflow.db.models import l2

LOG = log.getLogger(__name__)


class DHCPApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(DHCPApp, self).__init__(*args, **kwargs)
        self.idle_timeout = 30
        self.hard_timeout = 0

        cfg.CONF.register_opts(common_config.core_opts)
        self.conf = cfg.CONF.df_dhcp_app

        self.global_dns_list = self.conf.df_dns_servers
        self.lease_time = cfg.CONF.dhcp_lease_duration
        self.domain_name = cfg.CONF.dns_domain
        self.block_hard_timeout = self.conf.df_dhcp_block_time_in_sec
        self.default_interface_mtu = self.conf.df_default_network_device_mtu

        self.unique_key_to_dhcp_app_port_data = {}
        self.api.register_table_handler(const.DHCP_TABLE,
                                        self.packet_in_handler)
        self.switch_dhcp_ip_map = collections.defaultdict(dict)
        self.subnet_vm_port_map = collections.defaultdict(set)

    def switch_features_handler(self, ev):
        self._install_dhcp_broadcast_match_flow()
        self.add_flow_go_to_table(const.DHCP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)
        self.unique_key_to_dhcp_app_port_data.clear()
        self.switch_dhcp_ip_map.clear()
        self.subnet_vm_port_map.clear()

    def packet_in_handler(self, event):
        msg = event.msg

        pkt = ryu_packet.Packet(msg.data)
        pkt_ip = pkt.get_protocol(ipv4.ipv4)

        if not pkt_ip:
            LOG.error("No support for non IPv4 protocol")
            return

        unique_key = msg.match.get('reg6')
        port_data = self.unique_key_to_dhcp_app_port_data.get(unique_key)
        if not port_data:
            LOG.error(
                "No lport found for unique key %s for dhcp req",
                unique_key)
            return

        port_rate_limiter, lport = port_data
        if port_rate_limiter():
            self._block_port_dhcp_traffic(
                    unique_key,
                    self.block_hard_timeout)
            LOG.warning("pass rate limit for %(port_id)s blocking DHCP "
                        "traffic for %(time)s sec",
                        {'port_id': lport.id,
                         'time': self.block_hard_timeout})
            return
        if not self.db_store.get_one(lport):
            LOG.error("Port %s no longer found.", lport.id)
            return
        try:
            self._handle_dhcp_request(pkt, lport)
        except Exception:
            LOG.exception("Unable to handle packet %s", msg)

    def _handle_dhcp_request(self, packet, lport):
        dhcp_packet = packet.get_protocol(dhcp.dhcp)
        dhcp_message_type = self._get_dhcp_message_type_opt(dhcp_packet)
        send_packet = None
        if dhcp_message_type == dhcp.DHCP_DISCOVER:
            send_packet = self._create_dhcp_response(
                                packet,
                                dhcp_packet,
                                dhcp.DHCP_OFFER,
                                lport)
            LOG.info("sending DHCP offer for port IP %(port_ip)s "
                     "port id %(port_id)s",
                     {'port_ip': lport.ip, 'port_id': lport.id})
        elif dhcp_message_type == dhcp.DHCP_REQUEST:
            send_packet = self._create_dhcp_response(
                                packet,
                                dhcp_packet,
                                dhcp.DHCP_ACK,
                                lport)
            LOG.info("sending DHCP ACK for port IP %(port_ip)s "
                     "port id %(tunnel_id)s",
                     {'port_ip': lport.ip,
                      'tunnel_id': lport.id})
        else:
            LOG.error("DHCP message type %d not handled",
                      dhcp_message_type)
        if send_packet:
            unique_key = lport.unique_key
            self.dispatch_packet(send_packet, unique_key)

    def _create_dhcp_response(self, packet, dhcp_request,
                              response_type, lport):
        pkt_ipv4 = packet.get_protocol(ipv4.ipv4)
        pkt_ethernet = packet.get_protocol(ethernet.ethernet)

        try:
            subnet = lport.subnets[0]
        except IndexError:
            LOG.warning("No subnet found for port %s", lport.id)
            return

        dhcp_server_address = subnet.dhcp_ip
        if not dhcp_server_address:
            LOG.warning("Could not find DHCP server address for subnet %s",
                        subnet.id)
            return

        option_list = self._build_dhcp_options(dhcp_request,
                                               response_type,
                                               lport,
                                               subnet,
                                               dhcp_server_address)

        if not option_list:
            return

        options = dhcp.options(option_list=option_list)

        dhcp_server_address = subnet.dhcp_ip
        dhcp_response = ryu_packet.Packet()
        dhcp_response.add_protocol(ethernet.ethernet(
                                                ethertype=ether.ETH_TYPE_IP,
                                                dst=pkt_ethernet.src,
                                                src=pkt_ethernet.dst))
        dhcp_response.add_protocol(ipv4.ipv4(dst=pkt_ipv4.src,
                                             src=dhcp_server_address,
                                             proto=pkt_ipv4.proto))
        dhcp_response.add_protocol(udp.udp(src_port=const.DHCP_SERVER_PORT,
                                           dst_port=const.DHCP_CLIENT_PORT))

        dhcp_response.add_protocol(dhcp.dhcp(op=dhcp.DHCP_BOOT_REPLY,
                                             chaddr=pkt_ethernet.src,
                                             siaddr=dhcp_server_address,
                                             boot_file=dhcp_request.boot_file,
                                             yiaddr=lport.ip,
                                             xid=dhcp_request.xid,
                                             options=options))
        return dhcp_response


    def _build_dhcp_options(self, dhcp_request, response_type,
                            lport, subnet, srv_addr):

        """
        according the RFC the server need to response with
        with all the option that "explicitly configured options"
        and supply as many of the "requested parameters" as
        possible

        https://www.ietf.org/rfc/rfc2131.txt (page 29)
         """

        options_dict = {}

        # explicitly configured options
        self._build_response_default_options(response_type, lport,
                                             subnet, options_dict, srv_addr)

        # requested options
        self._build_requested_parmter_list(dhcp_request, lport, options_dict)

        option_list = []
        for option_tag in options_dict:
            option = dhcp.option(option_tag, options_dict[option_tag])
            option_list.append(option)

        return option_list

    def _build_response_default_options(self, response_type, lport,
                                        subnet, options_dict, srv_addr):
        pkt_type_packed = struct.pack('!B', response_type)
        dns = self._get_dns_address_list_bin(subnet)
        host_routes = self._get_host_routes_list_bin(subnet, lport)

        server_addr_bin = srv_addr.packed
        netmask_bin = subnet.cidr.netmask.packed
        domain_name_bin = struct.pack('!%ss' % len(self.domain_name),
                                      self.domain_name.encode())
        lease_time_bin = struct.pack('!I', self.lease_time)

        options_dict[dhcp.DHCP_MESSAGE_TYPE_OPT] = pkt_type_packed
        options_dict[dhcp.DHCP_SUBNET_MASK_OPT] = netmask_bin
        options_dict[dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT] = lease_time_bin
        options_dict[dhcp.DHCP_SERVER_IDENTIFIER_OPT] = server_addr_bin
        options_dict[dhcp.DHCP_DNS_SERVER_ADDR_OPT] = dns
        options_dict[dhcp.DHCP_DOMAIN_NAME_OPT] = domain_name_bin
        options_dict[dhcp.DHCP_CLASSLESS_ROUTE_OPT] = host_routes

        gw_ip = self._get_port_gateway_address(subnet, lport)
        if gw_ip:
            gw_ip_bin = netaddr.IPAddress(gw_ip).packed
            options_dict[dhcp.DHCP_GATEWAY_ADDR_OPT] = gw_ip_bin

        if response_type == dhcp.DHCP_ACK:
            intreface_mtu = self._get_port_mtu(lport)
            mtu_bin = struct.pack('!H', intreface_mtu)
            options_dict[dhcp.DHCP_INTERFACE_MTU_OPT] = mtu_bin

    def _build_requested_parmter_list(self, dhcp_request, lport, option_dict):

        req_list_opt = dhcp.DHCP_PARAMETER_REQUEST_LIST_OPT
        requested_opts = self._get_dhcp_option_by_tag(dhcp_request,
                                                      req_list_opt)
        if not requested_opts:
            return

        for opt in requested_opts:
            opt_int = ord(opt)
            if opt_int in option_dict:
                # already answered by the default options
                continue

            value = lport.extra_dhcp_options.get(opt_int)
            if value:
                option_dict[opt_int] = value

    def _get_dns_address_list_bin(self, subnet):
        dns_servers = self.global_dns_list
        if len(subnet.dns_nameservers) > 0:
            dns_servers = subnet.dns_nameservers
        dns_bin = b''
        for address in dns_servers:
            dns_bin += addrconv.ipv4.text_to_bin(address)
        return dns_bin

    def _get_host_routes_list_bin(self, subnet, lport):
        host_routes = copy.copy(subnet.host_routes)
        if self.conf.df_add_link_local_route:
            # Add route for metadata request.
            host_routes.append(host_route.HostRoute(
                destination='%s/32' % const.METADATA_SERVICE_IP,
                nexthop=lport.ip))

        routes_bin = b''

        opt = lport.extra_dhcp_options.get(dhcp.DHCP_CLASSLESS_ROUTE_OPT)
        if opt:
            dest_cidr, _c, via = opt.partition(',')
            host_routes.append(
                host_route.HostRoute(destination=dest_cidr,
                                     nexthop=via))

        for route in host_routes:
            dest = route.destination.network
            mask = route.destination.prefixlen
            routes_bin += struct.pack('B', mask)
            """
            for compact encoding
            Width of subnet mask      Number of significant octets
                            0               0
                         1- 8               1
                         9-16               2
                        17-24               3
                        25-32               4
            """
            addr_bin = addrconv.ipv4.text_to_bin(dest)
            dest_len = int(math.ceil(mask / 8.0))
            routes_bin += addr_bin[:dest_len]
            routes_bin += addrconv.ipv4.text_to_bin(route.nexthop)

        return routes_bin

    def _get_dhcp_option_by_tag(self, dhcp_packet, tag):
        if dhcp_packet.options:
            for opt in dhcp_packet.options.option_list:
                if opt.tag == tag:
                    return opt.value

    def _get_dhcp_message_type_opt(self, dhcp_packet):
        opt_value = self._get_dhcp_option_by_tag(dhcp_packet,
                                                 dhcp.DHCP_MESSAGE_TYPE_OPT)
        if opt_value:
            return ord(opt_value)

    def _get_port_gateway_address(self, subnet, lport):
        gateway_ip = subnet.gateway_ip
        if gateway_ip:
            return gateway_ip

        return lport.extra_dhcp_options.get(dhcp.DHCP_GATEWAY_ADDR_OPT)

    def _is_dhcp_enabled_for_port(self, lport):
        try:
            subnet = lport.subnets[0]
        except IndexError:
            LOG.warning("No subnet found for port %s", lport.id)
            return False
        return subnet.enable_dhcp

    def _get_port_mtu(self, lport):
        # get network mtu from lswitch
        lswitch = lport.lswitch
        mtu = lswitch.mtu
        tunnel_type = lswitch.network_type

        if tunnel_type == n_const.TYPE_VXLAN:
            return mtu - n_const.VXLAN_ENCAP_OVERHEAD if mtu else 0
        elif tunnel_type == n_const.TYPE_GENEVE:
            # TODO(gampel) use max_header_size param when we move to ML2
            return mtu - n_const.GENEVE_ENCAP_MIN_OVERHEAD if mtu else 0
        elif tunnel_type == n_const.TYPE_GRE:
            return mtu - n_const.GRE_ENCAP_OVERHEAD if mtu else 0
        return self.default_interface_mtu

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _remove_local_port(self, lport):
        if lport.ip.version != n_const.IP_VERSION_4:
            LOG.warning("No support for non IPv4 protocol")
            return

        unique_key = lport.unique_key
        self.unique_key_to_dhcp_app_port_data.pop(unique_key, None)

        subnet_id = lport.subnets[0].id
        self.subnet_vm_port_map[subnet_id].discard(lport.id)
        self._uninstall_dhcp_flow_for_vm_port(lport)

    def _uninstall_dhcp_flow_for_vm_port(self, lport):
        """Uninstall dhcp flow in DHCP_TABLE for a port of vm."""

        unique_key = lport.unique_key
        match = self.parser.OFPMatch(reg6=unique_key)
        self.mod_flow(
            table_id=const.DHCP_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    def _add_local_port(self, lport):
        if lport.ip.version != n_const.IP_VERSION_4:
            LOG.warning("No support for non IPv4 protocol")
            return

        if not lport.is_vm_port():
            return

        subnet_id = lport.subnets[0].id
        self.subnet_vm_port_map[subnet_id].add(lport.id)

        if not self._is_dhcp_enabled_for_port(lport):
            return

        self._install_dhcp_flow_for_vm_port(lport)

    def _install_dhcp_flow_for_vm_port(self, lport):
        """Install dhcp flow in DHCP_TABLE for a port of vm."""

        unique_key = lport.unique_key
        port_rate_limiter = df_utils.RateLimiter(
                        max_rate=self.conf.df_dhcp_max_rate_per_sec,
                        time_unit=1)
        self.unique_key_to_dhcp_app_port_data[unique_key] = (port_rate_limiter,
                                                             lport)

        LOG.info("Register VM as DHCP client::port <%s>", lport.id)

        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(reg6=unique_key)
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            inst=inst,
            table_id=const.DHCP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    @df_base_app.register_event(l2.LogicalSwitch,
                                model_constants.EVENT_CREATED)
    @df_base_app.register_event(l2.LogicalSwitch,
                                model_constants.EVENT_UPDATED)
    def update_logical_switch(self, lswitch, orig_lswitch=None):
        subnets = lswitch.subnets
        network_id = lswitch.unique_key
        all_subnets = set()
        for subnet in subnets:
            if self._is_ipv4(subnet):
                subnet_id = subnet.id
                all_subnets.add(subnet_id)
                old_dhcp_ip = (
                    (self.switch_dhcp_ip_map[network_id]
                     and self.switch_dhcp_ip_map[network_id].get(subnet_id))
                    or None)
                if subnet.enable_dhcp:
                    dhcp_ip = subnet.dhcp_ip
                    if dhcp_ip != old_dhcp_ip:
                        # In case the subnet alway has dhcp enabled, but change
                        # its dhcp IP.
                        self._install_dhcp_unicast_match_flow(dhcp_ip,
                                                              network_id)
                        if old_dhcp_ip:
                            self._remove_dhcp_unicast_match_flow(
                                network_id, old_dhcp_ip)
                        else:
                            # The first time the subnet is found as a dhcp
                            # enabled subnet. The vm's dhcp flow needs to be
                            # downloaded.
                            self._install_dhcp_flow_for_vm_in_subnet(subnet_id)

                        self.switch_dhcp_ip_map[network_id].update(
                            {subnet_id: dhcp_ip})
                else:
                    if old_dhcp_ip:
                        # The subnet was found as a dhcp enabled subnet, but it
                        # has been changed to dhcp disabled subnet now.
                        self._uninstall_dhcp_flow_for_vm_in_subnet(subnet_id)
                        self._remove_dhcp_unicast_match_flow(
                            network_id, old_dhcp_ip)
                        self.switch_dhcp_ip_map[network_id].update(
                            {subnet_id: None})

        # Clear stale dhcp ips, which belongs to the subnets that are deleted.
        deleted_subnets = (set(self.switch_dhcp_ip_map[network_id]) -
                           all_subnets)
        for subnet_id in deleted_subnets:
            dhcp_ip = self.switch_dhcp_ip_map[network_id][subnet_id]
            if dhcp_ip:
                self._remove_dhcp_unicast_match_flow(network_id, dhcp_ip)

            del self.switch_dhcp_ip_map[network_id][subnet_id]

    @df_base_app.register_event(l2.LogicalSwitch,
                                model_constants.EVENT_DELETED)
    def remove_logical_switch(self, lswitch):
        network_id = lswitch.unique_key
        self._remove_dhcp_unicast_match_flow(network_id)
        del self.switch_dhcp_ip_map[network_id]

    def _remove_dhcp_unicast_match_flow(self, network_id, ip_addr=None):
        parser = self.parser
        ofproto = self.ofproto
        if ip_addr:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    ipv4_dst=ip_addr,
                                    ip_proto=n_const.PROTO_NUM_UDP,
                                    udp_src=const.DHCP_CLIENT_PORT,
                                    udp_dst=const.DHCP_SERVER_PORT,
                                    metadata=network_id)
        else:
            match = parser.OFPMatch(metadata=network_id)
        self.mod_flow(
            table_id=const.SERVICES_CLASSIFICATION_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _install_dhcp_broadcast_match_flow(self):
        parser = self.parser

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                eth_dst=const.BROADCAST_MAC,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCP_CLIENT_PORT,
                                udp_dst=const.DHCP_SERVER_PORT)

        self.add_flow_go_to_table(const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.DHCP_TABLE, match=match)

    def _install_dhcp_unicast_match_flow(self, ip_addr, network_id):
        parser = self.parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ipv4_dst=ip_addr,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCP_CLIENT_PORT,
                                udp_dst=const.DHCP_SERVER_PORT,
                                metadata=network_id)

        self.add_flow_go_to_table(const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.DHCP_TABLE, match=match)

    def _install_dhcp_flow_for_vm_in_subnet(self, subnet_id):
        local_ports = self.subnet_vm_port_map[subnet_id]
        for p_id in local_ports:
            port = self.db_store.get_one(l2.LogicalPort(id=p_id))
            if port and port.is_local:
                self._install_dhcp_flow_for_vm_port(port)

    def _uninstall_dhcp_flow_for_vm_in_subnet(self, subnet_id):
        local_ports = self.subnet_vm_port_map[subnet_id]
        for p_id in local_ports:
            port = self.db_store.get_one(l2.LogicalPort(id=p_id))
            if port and port.is_local:
                self._uninstall_dhcp_flow_for_vm_port(port)

    def _is_ipv4(self, subnet):
        return subnet.cidr.version == n_const.IP_VERSION_4

    def _block_port_dhcp_traffic(self, unique_key, hard_timeout):
        match = self.parser.OFPMatch(reg6=unique_key)
        drop_inst = None
        self.mod_flow(
             inst=drop_inst,
             priority=const.PRIORITY_VERY_HIGH,
             hard_timeout=hard_timeout,
             table_id=const.DHCP_TABLE,
             match=match)
