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
from neutron.plugins.common import constants as n_p_const
from oslo_config import cfg
from oslo_log import log
from ryu.lib import addrconv
from ryu.lib.packet import dhcp
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet as ryu_packet
from ryu.lib.packet import udp
from ryu.ofproto import ether

from dragonflow.common import utils as df_utils
from dragonflow._i18n import _, _LI, _LE, _LW
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app

DF_DHCP_OPTS = [
    cfg.ListOpt('df_dns_servers',
        default=['8.8.8.8', '8.8.4.4'],
        help=_('Comma-separated list of the DNS servers which will be used.')),
    cfg.IntOpt('df_default_network_device_mtu', default=1460,
        help=_('default MTU setting for interface.')),
    cfg.IntOpt('df_dhcp_max_rate_per_sec', default=3,
        help=_('Port Max rate of DHCP messages per second')),
    cfg.IntOpt('df_dhcp_block_time_in_sec', default=100,
        help=_('Time to block port that passes the max rate')),
    cfg.BoolOpt('df_add_link_local_route', default=True,
        help=_("Set True to add route for link local address, which will be "
               "useful for metadata service.")),
]

LOG = log.getLogger(__name__)

DHCP_DOMAIN_NAME_OPT = 15
DHCP_INTERFACE_MTU_OPT = 26
DHCP_DISCOVER = 1
DHCP_OFFER = 2
DHCP_REQUEST = 3
DHCP_ACK = 5
DHCP_CLASSLESS_ROUTE = 121


class DHCPApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(DHCPApp, self).__init__(*args, **kwargs)
        self.idle_timeout = 30
        self.hard_timeout = 0

        cfg.CONF.register_opts(DF_DHCP_OPTS, 'df_dhcp_app')
        cfg.CONF.register_opts(common_config.core_opts)
        self.conf = cfg.CONF.df_dhcp_app

        self.global_dns_list = self.conf.df_dns_servers
        self.lease_time = cfg.CONF.dhcp_lease_duration
        self.domain_name = cfg.CONF.dns_domain
        self.advertise_mtu = cfg.CONF.advertise_mtu
        self.block_hard_timeout = self.conf.df_dhcp_block_time_in_sec
        self.default_interface_mtu = self.conf.df_default_network_device_mtu

        self.local_tunnel_to_pid_map = {}
        self.api.register_table_handler(const.DHCP_TABLE,
                self.packet_in_handler)
        self.switch_dhcp_ip_map = collections.defaultdict(set)

    def switch_features_handler(self, ev):
        self._install_dhcp_broadcast_match_flow()
        self.add_flow_go_to_table(self.get_datapath(),
                                  const.DHCP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)
        # TODO(gampel) handle network changes

    def packet_in_handler(self, event):
        msg = event.msg

        pkt = ryu_packet.Packet(msg.data)
        is_pkt_ipv4 = pkt.get_protocol(ipv4.ipv4) is not None

        if is_pkt_ipv4:
            pkt_ip = pkt.get_protocol(ipv4.ipv4)
        else:
            LOG.error(_LE("No support for non IpV4 protocol"))
            return

        if pkt_ip is None:
            LOG.error(_LE("Received None IP Packet"))
            return

        port_tunnel_key = msg.match.get('metadata')
        if port_tunnel_key not in self.local_tunnel_to_pid_map:
            LOG.error(
                _LE("No lport found for tunnel_id %s for dhcp req"),
                port_tunnel_key)
            return

        (port_rate_limiter,
            ofport_num,
            lport_id) = self.local_tunnel_to_pid_map[port_tunnel_key]
        if port_rate_limiter():
            self._block_port_dhcp_traffic(
                    ofport_num,
                    self.block_hard_timeout)
            LOG.warning(_LW("pass rate limit for %(port_id)s blocking DHCP"
                " traffic for %(time)s sec") %
                    {'port_id': lport_id,
                    'time': self.block_hard_timeout})
            return
        lport = self.db_store.get_port(lport_id)
        if lport is None:
            LOG.error(
                _LE("No lport found for tunnel_id %s for dhcp req"),
                port_tunnel_key)
            return
        try:
            self._handle_dhcp_request(msg, pkt, lport)
        except Exception as exception:
            LOG.exception(_LE(
                "Unable to handle packet %(msg)s: %(e)s")
                % {'msg': msg, 'e': exception}
            )

    def _handle_dhcp_request(self, msg, pkt, lport):
        packet = ryu_packet.Packet(data=msg.data)
        in_port = msg.match.get("in_port")

        if isinstance(packet[3], str):
            dhcp_packet = dhcp.dhcp.parser(packet[3])[0]
        else:
            dhcp_packet = packet[3]

        dhcp_message_type = self._get_dhcp_message_type_opt(dhcp_packet)
        send_packet = None
        if dhcp_message_type == DHCP_DISCOVER:
            #DHCP DISCOVER
            send_packet = self._create_dhcp_offer(
                                pkt,
                                dhcp_packet,
                                lport)
            LOG.info(_LI("sending DHCP offer for port IP %(port_ip)s"
                " port id %(port_id)s")
                     % {'port_ip': lport.get_ip(), 'port_id': lport.get_id()})
        elif dhcp_message_type == DHCP_REQUEST:
            #DHCP REQUEST
            send_packet = self._create_dhcp_ack(
                                pkt,
                                dhcp_packet,
                                lport)
            LOG.info(_LI("sending DHCP ACK for port IP %(port_ip)s"
                        " port id %(tunnel_id)s")
                        % {'port_ip': lport.get_ip(),
                        'tunnel_id': lport.get_id()})
        else:
            LOG.error(_LE("DHCP message type %d not handled"),
                dhcp_message_type)
        if send_packet:
            self._send_packet(self.get_datapath(), in_port, send_packet)

    def _create_dhcp_ack(self, pkt, dhcp_packet, lport):
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        subnet = self._get_subnet_by_port(lport)
        if subnet is None:
            LOG.error(_LE("No subnet found for port <%s>") %
                      lport.get_id())
            return

        dns = self._get_dns_address_list_bin(subnet)
        host_routes = self._get_host_routes_list_bin(subnet, lport)
        dhcp_server_address = str(self._get_dhcp_server_address(subnet))
        gateway_address = self._get_port_gateway_address(subnet)
        netmask_bin = self._get_port_netmask(subnet).packed
        domain_name_bin = struct.pack('!256s', self.domain_name)
        lease_time_bin = struct.pack('!I', self.lease_time)
        option_list = [
            dhcp.option(dhcp.DHCP_MESSAGE_TYPE_OPT, b'\x05', 1),
            dhcp.option(dhcp.DHCP_SUBNET_MASK_OPT, netmask_bin, 4),
            dhcp.option(dhcp.DHCP_GATEWAY_ADDR_OPT, gateway_address.packed, 4),
            dhcp.option(dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT,
                    lease_time_bin, 4),
            dhcp.option(dhcp.DHCP_DNS_SERVER_ADDR_OPT, dns, len(dns)),
            dhcp.option(DHCP_DOMAIN_NAME_OPT,
                    domain_name_bin,
                    len(self.domain_name)),
            dhcp.option(DHCP_CLASSLESS_ROUTE, host_routes, len(host_routes))]

        if self.advertise_mtu:
            intreface_mtu = self._get_port_mtu(lport)
            mtu_bin = struct.pack('!H', intreface_mtu)
            option_list.append(dhcp.option(
                                    DHCP_INTERFACE_MTU_OPT,
                                    mtu_bin,
                                    len(mtu_bin)))
        options = dhcp.options(option_list=option_list)
        dhcp_ack_pkt = ryu_packet.Packet()
        dhcp_ack_pkt.add_protocol(ethernet.ethernet(
                                                ethertype=ether.ETH_TYPE_IP,
                                                dst=pkt_ethernet.src,
                                                src=pkt_ethernet.dst))
        dhcp_ack_pkt.add_protocol(ipv4.ipv4(dst=pkt_ipv4.src,
                                  src=dhcp_server_address,
                                  proto=pkt_ipv4.proto))
        dhcp_ack_pkt.add_protocol(udp.udp(src_port=67, dst_port=68))
        dhcp_ack_pkt.add_protocol(dhcp.dhcp(op=2, chaddr=pkt_ethernet.src,
                                         siaddr=dhcp_server_address,
                                         boot_file=dhcp_packet.boot_file,
                                         yiaddr=lport.get_ip(),
                                         xid=dhcp_packet.xid,
                                         options=options))
        return dhcp_ack_pkt

    def _create_dhcp_offer(self, pkt, dhcp_packet, lport):
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        subnet = self._get_subnet_by_port(lport)
        if subnet is None:
            LOG.error(_LE("No subnet found for port <%s>") %
                      lport.get_id())
            return

        dns = self._get_dns_address_list_bin(subnet)
        host_routes = self._get_host_routes_list_bin(subnet, lport)
        dhcp_server_address = self._get_dhcp_server_address(subnet)
        netmask_bin = self._get_port_netmask(subnet).packed
        lease_time_bin = struct.pack('!I', self.lease_time)
        gateway_address = self._get_port_gateway_address(subnet)
        domain_name_bin = struct.pack('!256s', self.domain_name)

        option_list = [
            dhcp.option(dhcp.DHCP_MESSAGE_TYPE_OPT, b'\x02', 1),
            dhcp.option(dhcp.DHCP_SUBNET_MASK_OPT, netmask_bin, 4),
            dhcp.option(dhcp.DHCP_DNS_SERVER_ADDR_OPT, dns, len(dns)),
            dhcp.option(dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT,
                        lease_time_bin, 4),
            dhcp.option(dhcp.DHCP_SERVER_IDENTIFIER_OPT,
                        dhcp_server_address.packed, 4),
            dhcp.option(15, domain_name_bin, len(self.domain_name)),
            dhcp.option(DHCP_CLASSLESS_ROUTE, host_routes, len(host_routes))]
        if gateway_address:
            option_list.append(dhcp.option(
                                    dhcp.DHCP_GATEWAY_ADDR_OPT,
                                    gateway_address.packed,
                                    4))

        options = dhcp.options(option_list=option_list)
        dhcp_offer_pkt = ryu_packet.Packet()
        dhcp_offer_pkt.add_protocol(ethernet.ethernet(
                                    ethertype=ether.ETH_TYPE_IP,
                                    dst=pkt_ethernet.src,
                                    src=pkt_ethernet.dst))
        dhcp_offer_pkt.add_protocol(ipv4.ipv4(dst=pkt_ipv4.src,
                                   src=str(dhcp_server_address),
                                   proto=pkt_ipv4.proto))
        dhcp_offer_pkt.add_protocol(udp.udp(src_port=67, dst_port=68))
        dhcp_offer_pkt.add_protocol(dhcp.dhcp(op=2, chaddr=pkt_ethernet.src,
                                         siaddr=str(dhcp_server_address),
                                         boot_file=dhcp_packet.boot_file,
                                         yiaddr=lport.get_ip(),
                                         xid=dhcp_packet.xid,
                                         options=options))
        return dhcp_offer_pkt

    def _get_dns_address_list_bin(self, subnet):
        dns_servers = self.global_dns_list
        if len(subnet.get_dns_name_servers()) > 0:
            dns_servers = subnet.get_dns_name_servers()
        dns_bin = b''
        for address in dns_servers:
            dns_bin += addrconv.ipv4.text_to_bin(address)
        return dns_bin

    def _get_host_routes_list_bin(self, subnet, lport):
        host_routes = copy.copy(subnet.get_host_routes())
        if self.conf.df_add_link_local_route:
            # Add route for metadata request.
            host_routes.append(
                {'destination': '%s/32' % const.METADATA_SERVICE_IP,
                 'nexthop': lport.get_ip()})

        routes_bin = b''

        for route in host_routes:
            dest, slash, mask = route.get('destination').partition('/')
            mask = int(mask)
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
            routes_bin += addrconv.ipv4.text_to_bin(route.get('nexthop'))

        return routes_bin

    def _get_dhcp_message_type_opt(self, dhcp_packet):
        for opt in dhcp_packet.options.option_list:
            if opt.tag == dhcp.DHCP_MESSAGE_TYPE_OPT:
                return ord(opt.value)

    def _get_subnet_by_port(self, lport):
        l_switch_id = lport.get_lswitch_id()
        l_switch = self.db_store.get_lswitch(l_switch_id)
        subnets = l_switch.get_subnets()
        ip = netaddr.IPAddress(lport.get_ip())
        for subnet in subnets:
            if ip in netaddr.IPNetwork(subnet.get_cidr()):
                return subnet
        return None

    def _get_lswitch_by_port(self, lport):
        l_switch_id = lport.get_lswitch_id()
        l_switch = self.db_store.get_lswitch(l_switch_id)
        return l_switch

    def _get_dhcp_server_address(self, subnet):
        return netaddr.IPAddress(subnet.get_dhcp_server_address())

    def _get_port_gateway_address(self, subnet):
        return netaddr.IPAddress(subnet.get_gateway_ip())

    def _get_port_netmask(self, subnet):
        return netaddr.IPNetwork(subnet.get_cidr()).netmask

    def _is_dhcp_enabled_on_network(self, lport, net_id):
        subnet = self._get_subnet_by_port(lport)
        if subnet:
            return subnet.enable_dhcp()
        LOG.warning(_LW("No subnet found for port <%s>") %
                lport.get_id())
        return True

    def _get_port_mtu(self, lport):
        # get network mtu from lswitch
        mtu = self._get_lswitch_by_port(lport).get_mtu()

        tunnel_type = cfg.CONF.df.tunnel_type
        if tunnel_type == n_p_const.TYPE_VXLAN:
            return mtu - n_p_const.VXLAN_ENCAP_OVERHEAD if mtu else 0
        elif tunnel_type == n_p_const.TYPE_GENEVE:
            #TODO(gampel) use max_header_size param when we move to ML2
            return mtu - n_p_const.GENEVE_ENCAP_MIN_OVERHEAD if mtu else 0
        elif tunnel_type == n_p_const.TYPE_GRE:
            return mtu - n_p_const.GRE_ENCAP_OVERHEAD if mtu else 0
        return self.default_interface_mtu

    def remove_local_port(self, lport):

        tunnel_key = lport.get_tunnel_key()
        if tunnel_key in self.local_tunnel_to_pid_map:
            self.local_tunnel_to_pid_map.pop(tunnel_key, None)
        # Remove ingress classifier for port
        ofport = lport.get_external_value('ofport')
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.DHCP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _is_port_a_vm(self, lport):
        owner = lport.get_device_owner()
        if not owner or "compute" in owner:
            return True
        return False

    def add_local_port(self, lport):
        network_id = lport.get_external_value('local_network_id')
        if self.get_datapath() is None:
            return

        lport_id = lport.get_id()
        tunnel_key = lport.get_tunnel_key()
        ofport = lport.get_external_value('ofport')
        port_rate_limiter = df_utils.RateLimiter(
                        max_rate=self.conf.df_dhcp_max_rate_per_sec,
                        time_unit=1)
        self.local_tunnel_to_pid_map[tunnel_key] = (port_rate_limiter,
                                                    ofport,
                                                    lport_id)

        if not self._is_dhcp_enabled_on_network(lport, network_id):
            return

        if not self._is_port_a_vm(lport):
            return

        LOG.info(_LI("Register VM as DHCP client::port <%s>") % lport.get_id())

        ofport = lport.get_external_value('ofport')
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        actions = []
        actions.append(parser.OFPActionSetField(metadata=tunnel_key))
        actions.append(parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER))
        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.DHCP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def update_logical_switch(self, lswitch):
        subnets = lswitch.get_subnets()
        network_id = self.db_store.get_network_id(
            lswitch.get_id(),
        )
        all_dhcp_ips = set()
        for subnet in subnets:
            if self._is_ipv4(subnet) and subnet.enable_dhcp():
                dhcp_ip = subnet.get_dhcp_server_address()
                if dhcp_ip not in self.switch_dhcp_ip_map[network_id]:
                    self._install_dhcp_unicast_match_flow(dhcp_ip, network_id)
                    self.switch_dhcp_ip_map[network_id].add(dhcp_ip)
                all_dhcp_ips.add(dhcp_ip)
        deleted_dhcp_ips = (self.switch_dhcp_ip_map[network_id] -
                            all_dhcp_ips)
        for dhcp_ip in deleted_dhcp_ips:
            self._remove_dhcp_unicast_match_flow(network_id, dhcp_ip)
            self.switch_dhcp_ip_map[network_id].remove(dhcp_ip)

    def remove_logical_switch(self, lswitch):
        network_id = self.db_store.get_network_id(
            lswitch.get_id(),
        )
        self._remove_dhcp_unicast_match_flow(network_id)

    def _remove_dhcp_unicast_match_flow(self, network_id, ip_addr=None):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        if ip_addr:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                            ipv4_dst=ip_addr,
                            ip_proto=17,
                            udp_src=68,
                            udp_dst=67,
                            metadata=network_id)
        else:
            match = parser.OFPMatch(metadata=network_id)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.SERVICES_CLASSIFICATION_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _install_dhcp_broadcast_match_flow(self):
        parser = self.get_datapath().ofproto_parser

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                            eth_dst='ff:ff:ff:ff:ff:ff',
                            ip_proto=17,
                            udp_src=68,
                            udp_dst=67)

        self.add_flow_go_to_table(self.get_datapath(),
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.DHCP_TABLE, match=match)

    def _install_dhcp_unicast_match_flow(self, ip_addr, network_id):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                            ipv4_dst=ip_addr,
                            ip_proto=17,
                            udp_src=68,
                            udp_dst=67,
                            metadata=network_id)

        self.add_flow_go_to_table(self.get_datapath(),
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.DHCP_TABLE, match=match)

    def _is_ipv4(self, subnet):
        try:
            return (netaddr.IPNetwork(subnet.get_cidr()).version == 4)
        except TypeError:
            return False

    def _block_port_dhcp_traffic(self, ofport_num, hard_timeout):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_in_port(ofport_num)
        drop_inst = None
        self.mod_flow(
             self.get_datapath(),
             inst=drop_inst,
             priority=const.PRIORITY_VERY_HIGH,
             hard_timeout=hard_timeout,
             table_id=const.DHCP_TABLE,
             match=match)
