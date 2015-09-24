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

import netaddr
import struct

from oslo_config import cfg
from oslo_log import log

from neutron.common import config as common_config
from neutron.i18n import _, _LI, _LE, _LW

from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.lib import addrconv
from ryu.lib.packet import dhcp
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet as ryu_packet
from ryu.lib.packet import udp
from ryu.ofproto import ether
from ryu.ofproto import ofproto_v1_3

from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp

DF_DHCP_OPTS = [
    cfg.ListOpt('df_dns_servers',
        default=['8.8.8.8', '8.8.8.7'],
        help=_('Comma-separated list of the DNS servers which will be used.')),
    cfg.IntOpt('df_default_network_device_mtu', default=1460,
        help=_('default MTU setting for interface.')),
]

LOG = log.getLogger(__name__)

DHCP_DOMAIN_NAME_OPT = 15
DHCP_INTERFACE_MTU_OPT = 26
DHCP_DISCOVER = 1
DHCP_OFFER = 2
DHCP_REQUEST = 3
DHCP_ACK = 5


class DHCPApp(DFlowApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(DHCPApp, self).__init__(*args, **kwargs)
        self.dp = None
        self.idle_timeout = 30
        self.hard_timeout = 0
        self.db_store = kwargs['db_store']

        cfg.CONF.register_opts(DF_DHCP_OPTS)
        cfg.CONF.register_opts(common_config.core_opts)
        self.global_dns_list = cfg.CONF.df_dns_servers
        self.lease_time = cfg.CONF.dhcp_lease_duration
        self.domain_name = cfg.CONF.dns_domain
        self.advertise_mtu = cfg.CONF.advertise_mtu
        self.default_interface_mtu = cfg.CONF.df_default_network_device_mtu

        self.local_tunnel_to_pid_map = {}

    def start(self):
        super(DHCPApp, self).start()
        return 1

    def is_ready(self):
        return self.dp is not None

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        self.dp = ev.msg.datapath
        self._install_flows_on_switch_up()
        # TODO(gampel) handle network changes

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        pass

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def OF_packet_in_handler(self, event):
        msg = event.msg
        if msg.table_id != const.DHCP_TABLE:
            return

        pkt = ryu_packet.Packet(msg.data)
        is_pkt_ipv4 = pkt.get_protocol(ipv4.ipv4) is not None

        if is_pkt_ipv4:
            pkt_ip = pkt.get_protocol(ipv4.ipv4)
        else:
            LOG.error(_LE("No support for none IpV4 protocol"))
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

        lport_id = self.local_tunnel_to_pid_map[port_tunnel_key]
        lport = self.db_store.get_port(lport_id)
        if lport is None:
            LOG.error(
                _LE("No lport found for tunnel_id %s for dhcp req"),
                port_tunnel_key)
            return
        try:
            self._handle_dhcp_request(msg, pkt, lport)
        except Exception as exception:
            LOG.error(_LE(
                "Unable to handle packet %(msg)s: %(e)s")
                % {'msg': msg, 'e': exception}
            )

    def _handle_dhcp_request(self, msg, pkt, lport):
        packet = ryu_packet.Packet(data=msg.data)
        in_port = msg.match.get("in_port")
        dhcp_packet = dhcp.dhcp.parser(packet[3])
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
            self._send_packet(self.dp, in_port, send_packet)

    def _create_dhcp_ack(self, pkt, dhcp_packet, lport):
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        subnet = self._get_subnet_by_port(lport)
        if subnet is None:
            LOG.error(_LE("No subnet found for port <%s>") %
                      lport.get_id())
            return

        dns = self._get_dns_address_list_bin(subnet)
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
                    len(self.domain_name))]

        if self.advertise_mtu:
            intreface_mtu = self._get_port_mtu(lport)
            mtu_bin = struct.pack('!H', intreface_mtu)
            option_list.append(dhcp.option(
                                    DHCP_INTERFACE_MTU_OPT,
                                    mtu_bin,
                                    len(mtu_bin)))
        options = dhcp.options(option_list=option_list)
        dhcp_offer_pkt = ryu_packet.Packet()
        dhcp_offer_pkt.add_protocol(ethernet.ethernet(
                                                ethertype=ether.ETH_TYPE_IP,
                                                dst=pkt_ethernet.src,
                                                src=pkt_ethernet.dst))
        dhcp_offer_pkt.add_protocol(ipv4.ipv4(dst=pkt_ipv4.src,
                                   src=dhcp_server_address,
                                   proto=pkt_ipv4.proto))
        dhcp_offer_pkt.add_protocol(udp.udp(src_port=67, dst_port=68))
        dhcp_offer_pkt.add_protocol(dhcp.dhcp(op=2, chaddr=pkt_ethernet.src,
                                         siaddr=dhcp_server_address,
                                         boot_file=dhcp_packet[0].boot_file,
                                         yiaddr=lport.get_ip(),
                                         xid=dhcp_packet[0].xid,
                                         options=options))
        return dhcp_offer_pkt

    def _create_dhcp_offer(self, pkt, dhcp_packet, lport):
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        subnet = self._get_subnet_by_port(lport)
        if subnet is None:
            LOG.error(_LE("No subnet found for port <%s>") %
                      lport.get_id())
            return

        dns = self._get_dns_address_list_bin(subnet)
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
            dhcp.option(15, domain_name_bin, len(self.domain_name))]
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
                                         boot_file=dhcp_packet[0].boot_file,
                                         yiaddr=lport.get_ip(),
                                         xid=dhcp_packet[0].xid,
                                         options=options))
        return dhcp_offer_pkt

    def _get_dns_address_list_bin(self, subnet):
        dns_servers = self.global_dns_list
        if len(subnet.get_dns_name_servers()) > 0:
            dns_servers = subnet.get_dns_name_servers()
        dns_bin = ''
        for address in dns_servers:
            dns_bin += addrconv.ipv4.text_to_bin(address)
        return dns_bin

    def _get_dhcp_message_type_opt(self, dhcp_packet):
        for opt in dhcp_packet[0].options.option_list:
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
        #TODO(gampel) Get mtu from network object onec we add support
        return self.default_interface_mtu

    def remove_local_port(self, lport):

        tunnel_key = lport.get_tunnel_key()
        if tunnel_key in self.local_tunnel_to_pid_map:
            self.local_tunnel_to_pid_map.pop(tunnel_key, None)
        # Remove ingress classifier for port
        ofport = lport.get_external_value('ofport')
        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto
        match = parser.OFPMatch()
        match.set_in_port(ofport)

        msg = parser.OFPFlowMod(
            datapath=self.dp,
            cookie=0,
            cookie_mask=0,
            table_id=const.DHCP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)
        self.dp.send_msg(msg)

    def _is_port_a_vm(self, lport):
        owner = lport.get_device_owner()
        if not owner or "compute" in owner:
            return True
        return False

    def add_local_port(self, lport):
        network_id = lport.get_external_value('local_network_id')
        if self.dp is None:
            return

        lport_id = lport.get_id()
        tunnel_key = lport.get_tunnel_key()
        self.local_tunnel_to_pid_map[tunnel_key] = lport_id

        if not self._is_dhcp_enabled_on_network(lport, network_id):
            return

        if not self._is_port_a_vm(lport):
            return

        LOG.info(_LI("Regiter VM as DHCP client::port <%s>") % lport.get_id())

        ofport = lport.get_external_value('ofport')
        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        actions = []
        actions.append(parser.OFPActionSetField(metadata=tunnel_key))
        actions.append(parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER))
        inst = [self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.DHCP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _install_dhcp_match_flow(self):
        parser = self.dp.ofproto_parser

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                            eth_dst='ff:ff:ff:ff:ff:ff',
                            ip_proto=17,
                            udp_src=68,
                            udp_dst=67)

        self.add_flow_go_to_table(self.dp,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.DHCP_TABLE, match=match)

    def _install_flows_on_switch_up(self):
        self._install_dhcp_match_flow()
        self.add_flow_go_to_table(self.dp,
                                  const.DHCP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)

        for port in self.db_store.get_ports():
            if port.get_external_value('is_local'):
                self.add_local_port(port)

    def add_remote_port(self, lport):
        pass

    def remove_remote_port(self, lport_id):
        pass

    def logical_switch_deleted(self, lswitch_id):
        pass

    def logical_switch_updated(self, lswitch):
        pass
