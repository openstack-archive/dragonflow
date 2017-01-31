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
from dragonflow._i18n import _LI, _LE, _LW
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app

LOG = log.getLogger(__name__)

DHCP_DOMAIN_NAME_OPT = 15
DHCP_INTERFACE_MTU_OPT = 26
DHCP_CLASSLESS_ROUTE_OPT = 121


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

        self.ofport_to_dhcp_app_port_data = {}
        self.api.register_table_handler(const.DHCP_TABLE,
                self.packet_in_handler)
        self.switch_dhcp_ip_map = collections.defaultdict(dict)
        self.subnet_vm_port_map = collections.defaultdict(set)

    def switch_features_handler(self, ev):
        self._install_dhcp_broadcast_match_flow()
        self.add_flow_go_to_table(const.DHCP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)
        self.ofport_to_dhcp_app_port_data.clear()
        self.switch_dhcp_ip_map.clear()
        self.subnet_vm_port_map.clear()

    def packet_in_handler(self, event):
        msg = event.msg

        pkt = ryu_packet.Packet(msg.data)
        pkt_ip = pkt.get_protocol(ipv4.ipv4)

        if not pkt_ip:
            LOG.error(_LE("No support for non IPv4 protocol"))
            return

        ofport = msg.match.get('in_port')
        port_data = self.ofport_to_dhcp_app_port_data.get(ofport)
        if not port_data:
            LOG.error(
                _LE("No lport found for ofport %s for dhcp req"),
                ofport)
            return

        port_rate_limiter, lport = port_data
        if port_rate_limiter():
            self._block_port_dhcp_traffic(
                    ofport,
                    self.block_hard_timeout)
            LOG.warning(_LW("pass rate limit for %(port_id)s blocking DHCP"
                " traffic for %(time)s sec") %
                    {'port_id': lport.get_id(),
                    'time': self.block_hard_timeout})
            return
        if not self.db_store.get_port(lport.get_id()):
            LOG.error(_LE("Port %s no longer found."), lport.get_id())
            return
        try:
            self._handle_dhcp_request(pkt, lport, ofport)
        except Exception:
            LOG.exception(_LE("Unable to handle packet %s"), msg)

    def _handle_dhcp_request(self, packet, lport, ofport):
        dhcp_packet = packet.get_protocol(dhcp.dhcp)
        dhcp_message_type = self._get_dhcp_message_type_opt(dhcp_packet)
        send_packet = None
        if dhcp_message_type == dhcp.DHCP_DISCOVER:
            send_packet = self._create_dhcp_packet(
                                packet,
                                dhcp_packet,
                                dhcp.DHCP_OFFER,
                                lport)
            LOG.info(_LI("sending DHCP offer for port IP %(port_ip)s"
                " port id %(port_id)s")
                     % {'port_ip': lport.get_ip(), 'port_id': lport.get_id()})
        elif dhcp_message_type == dhcp.DHCP_REQUEST:
            send_packet = self._create_dhcp_packet(
                                packet,
                                dhcp_packet,
                                dhcp.DHCP_ACK,
                                lport)
            LOG.info(_LI("sending DHCP ACK for port IP %(port_ip)s"
                        " port id %(tunnel_id)s")
                        % {'port_ip': lport.get_ip(),
                        'tunnel_id': lport.get_id()})
        else:
            LOG.error(_LE("DHCP message type %d not handled"),
                dhcp_message_type)
        if send_packet:
            self.send_packet(ofport, send_packet)

    def _create_dhcp_packet(self, packet, dhcp_packet, pkt_type, lport):
        pkt_ipv4 = packet.get_protocol(ipv4.ipv4)
        pkt_ethernet = packet.get_protocol(ethernet.ethernet)

        subnet = self._get_subnet_by_port(lport)
        if subnet is None:
            LOG.error(_LE("No subnet found for port <%s>") %
                      lport.get_id())
            return

        pkt_type_packed = struct.pack('!B', pkt_type)
        dns = self._get_dns_address_list_bin(subnet)
        host_routes = self._get_host_routes_list_bin(subnet, lport)
        dhcp_server_address = self._get_dhcp_server_address(subnet)
        netmask_bin = self._get_port_netmask(subnet).packed
        domain_name_bin = struct.pack('!%ss' % len(self.domain_name),
                                      self.domain_name)
        lease_time_bin = struct.pack('!I', self.lease_time)
        option_list = [
            dhcp.option(dhcp.DHCP_MESSAGE_TYPE_OPT, pkt_type_packed),
            dhcp.option(dhcp.DHCP_SUBNET_MASK_OPT, netmask_bin),
            dhcp.option(dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT, lease_time_bin),
            dhcp.option(dhcp.DHCP_SERVER_IDENTIFIER_OPT,
                        dhcp_server_address.packed),
            dhcp.option(dhcp.DHCP_DNS_SERVER_ADDR_OPT, dns),
            dhcp.option(DHCP_DOMAIN_NAME_OPT, domain_name_bin),
            dhcp.option(DHCP_CLASSLESS_ROUTE_OPT, host_routes),
        ]
        gw_ip = self._get_port_gateway_address(subnet, lport)
        if gw_ip:
            option_list.append(dhcp.option(dhcp.DHCP_GATEWAY_ADDR_OPT,
                                           netaddr.IPAddress(gw_ip).packed))

        if pkt_type == dhcp.DHCP_ACK:
            intreface_mtu = self._get_port_mtu(lport)
            mtu_bin = struct.pack('!H', intreface_mtu)
            option_list.append(dhcp.option(DHCP_INTERFACE_MTU_OPT, mtu_bin))
        options = dhcp.options(option_list=option_list)
        dhcp_pkt = ryu_packet.Packet()
        dhcp_pkt.add_protocol(ethernet.ethernet(
                                                ethertype=ether.ETH_TYPE_IP,
                                                dst=pkt_ethernet.src,
                                                src=pkt_ethernet.dst))
        dhcp_pkt.add_protocol(ipv4.ipv4(dst=pkt_ipv4.src,
                                  src=dhcp_server_address,
                                  proto=pkt_ipv4.proto))
        dhcp_pkt.add_protocol(udp.udp(src_port=const.DHCP_SERVER_PORT,
                                      dst_port=const.DHCP_CLIENT_PORT))
        dhcp_pkt.add_protocol(dhcp.dhcp(op=dhcp.DHCP_BOOT_REPLY,
                                        chaddr=pkt_ethernet.src,
                                        siaddr=dhcp_server_address,
                                        boot_file=dhcp_packet.boot_file,
                                        yiaddr=lport.get_ip(),
                                        xid=dhcp_packet.xid,
                                        options=options))
        return dhcp_pkt

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

        dhcp_opts = lport.get_extra_dhcp_opts()
        for opt in dhcp_opts:
            if opt['opt_name'] == str(DHCP_CLASSLESS_ROUTE_OPT):
                dest_cidr, _c, via = opt['opt_value'].partition(',')
                host_routes.append({'destination': dest_cidr, 'nexthop': via})

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
        subnet_id = lport.get_subnets()[0]
        for subnet in subnets:
            if subnet_id == subnet.get_id():
                return subnet
        return None

    def _get_lswitch_by_port(self, lport):
        l_switch_id = lport.get_lswitch_id()
        l_switch = self.db_store.get_lswitch(l_switch_id)
        return l_switch

    def _get_dhcp_server_address(self, subnet):
        return netaddr.IPAddress(subnet.get_dhcp_server_address())

    def _get_port_gateway_address(self, subnet, lport):
        gateway_ip = subnet.get_gateway_ip()
        if gateway_ip:
            return gateway_ip

        dhcp_opts = lport.get_extra_dhcp_opts()
        for opt in dhcp_opts:
            if opt['opt_name'] == str(dhcp.DHCP_GATEWAY_ADDR_OPT):
                return opt['opt_value']

    def _get_port_netmask(self, subnet):
        return netaddr.IPNetwork(subnet.get_cidr()).netmask

    def _is_dhcp_enabled_for_port(self, lport):
        subnet = self._get_subnet_by_port(lport)
        if subnet:
            return subnet.enable_dhcp()
        LOG.warning(_LW("No subnet found for port %s"), lport.get_id())
        return False

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
        if not netaddr.valid_ipv4(lport.get_ip()):
            LOG.warning(_LW("No support for non IPv4 protocol"))
            return

        ofport = lport.get_external_value('ofport')
        self.ofport_to_dhcp_app_port_data.pop(ofport, None)

        subnet_id = lport.get_subnets()[0]
        self.subnet_vm_port_map[subnet_id].discard(lport.get_id())
        self._uninstall_dhcp_flow_for_vm_port(lport)

    def _uninstall_dhcp_flow_for_vm_port(self, lport):
        """Uninstall dhcp flow in DHCP_TABLE for a port of vm."""

        ofport = lport.get_external_value('ofport')
        match = self.parser.OFPMatch()
        match.set_in_port(ofport)
        self.mod_flow(
            table_id=const.DHCP_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _is_vm_port(self, lport):
        owner = lport.get_device_owner()
        if not owner or "compute" in owner:
            return True
        return False

    def add_local_port(self, lport):
        if not netaddr.valid_ipv4(lport.get_ip()):
            LOG.warning(_LW("No support for non IPv4 protocol"))
            return

        if not self._is_vm_port(lport):
            return

        subnet_id = lport.get_subnets()[0]
        self.subnet_vm_port_map[subnet_id].add(lport.get_id())

        if not self._is_dhcp_enabled_for_port(lport):
            return

        self._install_dhcp_flow_for_vm_port(lport)

    def _install_dhcp_flow_for_vm_port(self, lport):
        """Install dhcp flow in DHCP_TABLE for a port of vm."""

        ofport = lport.get_external_value('ofport')
        port_rate_limiter = df_utils.RateLimiter(
                        max_rate=self.conf.df_dhcp_max_rate_per_sec,
                        time_unit=1)
        self.ofport_to_dhcp_app_port_data[ofport] = (port_rate_limiter, lport)

        LOG.info(_LI("Register VM as DHCP client::port <%s>"), lport.get_id())

        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(in_port=ofport)
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            inst=inst,
            table_id=const.DHCP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def update_logical_switch(self, lswitch):
        subnets = lswitch.get_subnets()
        network_id = lswitch.get_unique_key()
        all_subnets = set()
        for subnet in subnets:
            if self._is_ipv4(subnet):
                subnet_id = subnet.get_id()
                all_subnets.add(subnet_id)
                old_dhcp_ip = (
                    (self.switch_dhcp_ip_map[network_id]
                     and self.switch_dhcp_ip_map[network_id].get(subnet_id))
                    or None)
                if subnet.enable_dhcp():
                    dhcp_ip = subnet.get_dhcp_server_address()
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

    def remove_logical_switch(self, lswitch):
        network_id = lswitch.get_unique_key()
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
            port = self.db_store.get_local_port(p_id)
            if port:
                self._install_dhcp_flow_for_vm_port(port)

    def _uninstall_dhcp_flow_for_vm_in_subnet(self, subnet_id):
        local_ports = self.subnet_vm_port_map[subnet_id]
        for p_id in local_ports:
            port = self.db_store.get_local_port(p_id)
            if port:
                self._uninstall_dhcp_flow_for_vm_port(port)

    def _is_ipv4(self, subnet):
        try:
            return (netaddr.IPNetwork(subnet.get_cidr()).version == 4)
        except TypeError:
            return False

    def _block_port_dhcp_traffic(self, ofport_num, hard_timeout):
        match = self.parser.OFPMatch()
        match.set_in_port(ofport_num)
        drop_inst = None
        self.mod_flow(
             inst=drop_inst,
             priority=const.PRIORITY_VERY_HIGH,
             hard_timeout=hard_timeout,
             table_id=const.DHCP_TABLE,
             match=match)
