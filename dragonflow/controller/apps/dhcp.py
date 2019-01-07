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
import functools
import math
import struct

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
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import icmp_responder
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
        self._port_rate_limiters = collections.defaultdict(
            functools.partial(df_utils.RateLimiter,
                              max_rate=self.conf.df_dhcp_max_rate_per_sec,
                              time_unit=1))
        self.api.register_table_handler(const.DHCP_TABLE,
                                        self.packet_in_handler)
        self._dhcp_ip_by_subnet = {}

    def _get_dhcp_port_by_network(self, network_unique_key):

        lswitch = self.db_store.get_one(l2.LogicalSwitch(
            unique_key=network_unique_key),
            index=l2.LogicalSwitch.get_index('unique_key'))

        return self.db_store.get_one(
            l2.LogicalPort(
                device_owner=n_const.DEVICE_OWNER_DHCP,
                lswitch=lswitch
            ),
            index=l2.LogicalPort.get_index('switch,owner')
        )

    def switch_features_handler(self, ev):
        self._install_dhcp_packet_match_flow()
        self.add_flow_go_to_table(const.DHCP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)
        self._port_rate_limiters.clear()

    def _check_port_limit(self, lport):

        port_rate_limiter = self._port_rate_limiters[lport.id]

        return port_rate_limiter()

    def packet_in_handler(self, event):
        msg = event.msg

        pkt = ryu_packet.Packet(msg.data)
        pkt_ip = pkt.get_protocol(ipv4.ipv4)

        if not pkt_ip:
            LOG.error("No support for non IPv4 protocol")
            return

        unique_key = msg.match.get('reg6')
        lport = self.db_store.get_one(
            l2.LogicalPort(unique_key=unique_key),
            index=l2.LogicalPort.get_index('unique_key'),
        )

        network_key = msg.match.get('metadata')
        dhcp_lport = self._get_dhcp_port_by_network(network_key)
        if not dhcp_lport:
            LOG.error("No DHCP port for network {}".format(str(network_key)))
            return

        if self._check_port_limit(lport):
            self._block_port_dhcp_traffic(unique_key, lport)
            LOG.warning("pass rate limit for %(port_id)s blocking DHCP "
                        "traffic for %(time)s sec",
                        {'port_id': lport.id,
                         'time': self.block_hard_timeout})
            return

        if not self.db_store.get_one(lport):
            LOG.error("Port %s no longer found.", lport.id)
            return
        try:
            self._handle_dhcp_request(pkt, lport, dhcp_lport)
        except Exception:
            LOG.exception("Unable to handle packet %s", msg)

    def _handle_dhcp_request(self, packet, lport, dhcp_port):
        dhcp_packet = packet.get_protocol(dhcp.dhcp)
        dhcp_message_type = self._get_dhcp_message_type_opt(dhcp_packet)
        send_packet = None
        if dhcp_message_type == dhcp.DHCP_DISCOVER:
            send_packet = self._create_dhcp_response(
                                packet,
                                dhcp_packet,
                                dhcp.DHCP_OFFER,
                                lport,
                                dhcp_port)
            LOG.info("sending DHCP offer for port IP %(port_ip)s "
                     "port id %(port_id)s",
                     {'port_ip': lport.ip, 'port_id': lport.id})
        elif dhcp_message_type == dhcp.DHCP_REQUEST:
            send_packet = self._create_dhcp_response(
                                packet,
                                dhcp_packet,
                                dhcp.DHCP_ACK,
                                lport,
                                dhcp_port)
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
                              response_type, lport, dhcp_port):
        pkt_ipv4 = packet.get_protocol(ipv4.ipv4)
        pkt_ethernet = packet.get_protocol(ethernet.ethernet)

        try:
            subnet = lport.subnets[0]
        except IndexError:
            LOG.warning("No subnet found for port %s", lport.id)
            return

        dhcp_server_address = self._dhcp_ip_by_subnet.get(subnet.id)
        if not dhcp_server_address:
            LOG.warning("Could not find DHCP server address for subnet %s",
                        subnet.id)
            return

        option_list = self._build_dhcp_options(dhcp_request,
                                               response_type,
                                               lport,
                                               subnet,
                                               dhcp_server_address)

        options = dhcp.options(option_list=option_list)

        dhcp_response = ryu_packet.Packet()
        dhcp_response.add_protocol(ethernet.ethernet(
                                                ethertype=ether.ETH_TYPE_IP,
                                                dst=pkt_ethernet.src,
                                                src=dhcp_port.mac))
        dhcp_response.add_protocol(ipv4.ipv4(dst=pkt_ipv4.src,
                                             src=dhcp_server_address,
                                             proto=pkt_ipv4.proto))
        dhcp_response.add_protocol(udp.udp(src_port=const.DHCP_SERVER_PORT,
                                           dst_port=const.DHCP_CLIENT_PORT))

        siaddr = lport.dhcp_params.siaddr or dhcp_server_address

        dhcp_response.add_protocol(dhcp.dhcp(op=dhcp.DHCP_BOOT_REPLY,
                                             chaddr=pkt_ethernet.src,
                                             siaddr=siaddr,
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

        # explicitly configured options
        default_opts = self._build_response_default_options(response_type,
                                                            lport, subnet,
                                                            srv_addr)

        # requested options (according to dhcp_params.opt)
        response_opts = self._build_response_requested_options(dhcp_request,
                                                               lport,
                                                               default_opts)

        response_opts.update(default_opts)

        option_list = [dhcp.option(tag, value)
                       for tag, value in response_opts.items()]

        return option_list

    def _build_response_default_options(self, response_type, lport,
                                        subnet, srv_addr):
        options_dict = {}
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
            gw_ip_bin = gw_ip.packed
            options_dict[dhcp.DHCP_GATEWAY_ADDR_OPT] = gw_ip_bin

        if response_type == dhcp.DHCP_ACK:
            interface_mtu = self._get_port_mtu(lport)
            mtu_bin = struct.pack('!H', interface_mtu)
            options_dict[dhcp.DHCP_INTERFACE_MTU_OPT] = mtu_bin

        return options_dict

    def _build_response_requested_options(self, dhcp_request,
                                          lport, default_opts):
        options_dict = {}
        req_list_opt = dhcp.DHCP_PARAMETER_REQUEST_LIST_OPT
        requested_opts = self._get_dhcp_option_by_tag(dhcp_request,
                                                      req_list_opt)
        if not requested_opts:
            return {}

        for opt in requested_opts:
            # For python3 opt is already int.
            if isinstance(opt, str):
                opt_int = ord(opt)
            else:
                opt_int = opt

            if opt_int in default_opts:
                # already answered by the default options
                continue

            value = lport.dhcp_params.opts.get(opt_int)
            if value:
                value_bin = struct.pack('!%ss' % len(value),
                                        value.encode())
                options_dict[opt_int] = value_bin

        return options_dict

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
        opt = lport.dhcp_params.opts.get(dhcp.DHCP_CLASSLESS_ROUTE_OPT)
        if opt:
            dest_cidr, _c, via = opt.partition(',')
            host_routes.append(
                host_route.HostRoute(destination=dest_cidr,
                                     nexthop=via))

        # We must add the default route here. if a host supports classless
        # route options, it must ignore the router option
        gateway = self._get_port_gateway_address(subnet, lport)
        if gateway is not None:
            host_routes.append(
                host_route.HostRoute(
                    destination='0.0.0.0/0',
                    nexthop=gateway,
                ),
            )

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
        return lport.dhcp_params.opts.get(dhcp.DHCP_GATEWAY_ADDR_OPT)

    def _get_port_mtu(self, lport):
        # get network mtu from lswitch
        lswitch = lport.lswitch
        mtu = lswitch.mtu
        if mtu:
            return mtu
        return self.default_interface_mtu

    def _install_dhcp_classification_flow(self):
        parser = self.parser

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCP_CLIENT_PORT,
                                udp_dst=const.DHCP_SERVER_PORT)

        self.add_flow_go_to_table(const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.DHCP_TABLE, match=match)

    def _block_port_dhcp_traffic(self, unique_key, lport):
        match = self.parser.OFPMatch(reg6=unique_key)
        drop_inst = None
        self.mod_flow(
             inst=drop_inst,
             priority=const.PRIORITY_VERY_HIGH,
             hard_timeout=self.block_hard_timeout,
             table_id=const.DHCP_TABLE,
             match=match)

    def _install_dhcp_packet_match_flow(self):
        parser = self.parser

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCP_CLIENT_PORT,
                                udp_dst=const.DHCP_SERVER_PORT)

        self.add_flow_go_to_table(const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.DHCP_TABLE, match=match)

    def _install_dhcp_port_flow(self, lswitch):
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(metadata=lswitch.unique_key)
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            inst=inst,
            table_id=const.DHCP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_dhcp_network_flow(self, lswitch):
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(metadata=lswitch.unique_key)
        self.mod_flow(
            table_id=const.DHCP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _add_dhcp_ips_by_subnet(self, lport):
        subnet_ids = (subnet.id for subnet in lport.subnets)
        self._dhcp_ip_by_subnet.update(dict(zip(subnet_ids, lport.ips)))

    @df_base_app.register_event(l2.LogicalPort, model_constants.EVENT_CREATED)
    def _lport_created(self, lport):
        if lport.device_owner != n_const.DEVICE_OWNER_DHCP:
            return

        self._install_dhcp_port_responders(lport)
        self._install_dhcp_port_flow(lport.lswitch)

        self._add_dhcp_ips_by_subnet(lport)

    def _update_port_responders(self, lport, orig_lport):
        self._uninstall_dhcp_port_responders(orig_lport)
        self._install_dhcp_port_responders(lport)

    def _update_dhcp_ips_by_subnet(self, lport, orig_lport):

        self._add_dhcp_ips_by_subnet(lport)

        orig_subnets = set(subnet.id for subnet in orig_lport.subnets)
        new_subnets = set(subnet.id for subnet in lport.subnets)

        deleted_subnets = orig_subnets - new_subnets
        for subnet_id in deleted_subnets:
            del self._dhcp_ip_by_subnet[subnet_id]

    def _delete_lport_rate_limiter(self, lport):
        if not lport.is_local:
            return

        if lport.id in self._port_rate_limiters:
            del self._port_rate_limiters[lport.id]

    @df_base_app.register_event(l2.LogicalPort, model_constants.EVENT_UPDATED)
    def _lport_updated(self, lport, orig_lport):
        if lport.device_owner != n_const.DEVICE_OWNER_DHCP:
            return

        v4_ips = set(ip for ip in lport.ips if
                     ip.version == n_const.IP_VERSION_4)
        v4_old_ips = set(ip for ip in orig_lport.ips
                         if ip.version == n_const.IP_VERSION_4)

        if v4_ips != v4_old_ips or lport.mac != orig_lport.mac:
            self._update_port_responders(lport, orig_lport)

        self._update_dhcp_ips_by_subnet(lport, orig_lport)

    def _delete_dhcp_ips_by_subnet(self, lport):
        for subnet in lport.subnets:
            del self._dhcp_ip_by_subnet[subnet.id]

    @df_base_app.register_event(l2.LogicalPort, model_constants.EVENT_DELETED)
    def _lport_deleted(self, lport):
        if lport.device_owner != n_const.DEVICE_OWNER_DHCP:
            self._delete_lport_rate_limiter(lport)
            return

        self._uninstall_dhcp_port_responders(lport)
        self._remove_dhcp_network_flow(lport.lswitch)
        self._delete_dhcp_ips_by_subnet(lport)

    def _install_dhcp_port_responders(self, lport):
        ips_v4 = (ip for ip in lport.ips
                  if ip.version == n_const.IP_VERSION_4)
        for ip in ips_v4:
            icmp_responder.ICMPResponder(
                app=self,
                network_id=lport.lswitch.unique_key,
                interface_ip=lport.ip,
                table_id=const.L2_LOOKUP_TABLE,
            ).add()

            arp_responder.ArpResponder(
                app=self,
                network_id=lport.lswitch.unique_key,
                interface_ip=ip,
                interface_mac=lport.mac,
            ).add()

    def _uninstall_dhcp_port_responders(self, lport):
        ips_v4 = (ip for ip in lport.ips
                  if ip.version == n_const.IP_VERSION_4)
        for ip in ips_v4:
            icmp_responder.ICMPResponder(
                app=self,
                network_id=lport.lswitch.unique_key,
                interface_ip=lport.ip,
                table_id=const.L2_LOOKUP_TABLE,
            ).remove()

            arp_responder.ArpResponder(
                app=self,
                network_id=lport.lswitch.unique_key,
                interface_ip=ip,
                interface_mac=lport.mac,
            ).remove()
