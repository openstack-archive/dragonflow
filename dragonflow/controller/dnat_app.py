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

import collections

from neutron_lib import constants as n_const
from oslo_log import log
from ryu.lib.packet import ethernet
from ryu.lib.packet import icmp
from ryu.lib.packet import in_proto
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import icmp_error_generator
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import l3


LOG = log.getLogger(__name__)

EGRESS = 'egress'

INGRESS = 'ingress'


def _fip_status_by_lport(fip):
    if fip.lport is None:
        return n_const.FLOATINGIP_STATUS_DOWN
    else:
        return n_const.FLOATINGIP_STATUS_ACTIVE


class DNATApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(DNATApp, self).__init__(*args, **kwargs)
        self.conf = cfg.CONF.df_dnat_app
        self.local_floatingips = collections.defaultdict(str)
        # Map between fixed ip mac to floating ip
        self.fip_port_key_cache = {}
        self.egress_ttl_invalid_handler_rate_limit = df_utils.RateLimiter(
            max_rate=self.conf.dnat_ttl_invalid_max_rate,
            time_unit=1)
        self.ingress_ttl_invalid_handler_rate_limit = df_utils.RateLimiter(
            max_rate=self.conf.dnat_ttl_invalid_max_rate,
            time_unit=1)
        self.egress_icmp_error_rate_limit = df_utils.RateLimiter(
            max_rate=self.conf.dnat_icmp_error_max_rate,
            time_unit=1)
        self.ingress_icmp_error_rate_limit = df_utils.RateLimiter(
            max_rate=self.conf.dnat_icmp_error_max_rate,
            time_unit=1)
        self.api.register_table_handler(const.INGRESS_DNAT_TABLE,
                                        self.ingress_packet_in_handler)
        self.api.register_table_handler(const.EGRESS_DNAT_TABLE,
                                        self.egress_packet_in_handler)

    def switch_features_handler(self, ev):
        self.local_floatingips.clear()
        self.fip_port_key_cache.clear()

    def _handle_ingress_invalid_ttl(self, event):
        LOG.debug("Get an invalid TTL packet at table %s",
                  const.INGRESS_DNAT_TABLE)

        if self.ingress_ttl_invalid_handler_rate_limit():
            LOG.warning("Get more than %(rate)s TTL invalid "
                        "packets per second at table %(table)s",
                        {'rate': self.conf.dnat_ttl_invalid_max_rate,
                         'table': const.INGRESS_DNAT_TABLE})
            return

        msg = event.msg

        icmp_ttl_pkt = icmp_error_generator.generate(
            icmp.ICMP_TIME_EXCEEDED, icmp.ICMP_TTL_EXPIRED_CODE, msg.data)
        network_id = msg.match.get('metadata')
        self.reinject_packet(
            icmp_ttl_pkt,
            table_id=const.L2_LOOKUP_TABLE,
            actions=[self.parser.OFPActionSetField(metadata=network_id)]
        )

    def _handle_ingress_icmp_translate(self, event):
        if self.ingress_icmp_error_rate_limit():
            LOG.warning("Get more than %(rate)s ICMP error messages "
                        "per second at table %(table)s",
                        {'rate': self.conf.dnat_icmp_error_max_rate,
                         'table': const.INGRESS_DNAT_TABLE})
            return

        msg = event.msg
        pkt = packet.Packet(msg.data)
        reply_pkt = self._revert_nat_for_icmp_embedded_packet(pkt, INGRESS)
        port_key = msg.match.get('reg7')
        self.dispatch_packet(reply_pkt, port_key)

    def ingress_packet_in_handler(self, event):
        if event.msg.reason == self.ofproto.OFPR_INVALID_TTL:
            self._handle_ingress_invalid_ttl(event)
        else:
            self._handle_ingress_icmp_translate(event)

    def _handle_egress_invalid_ttl(self, event):
        LOG.debug("Get an invalid TTL packet at table %s",
                  const.EGRESS_DNAT_TABLE)

        if self.egress_ttl_invalid_handler_rate_limit():
            LOG.warning("Get more than %(rate)s TTL invalid "
                        "packets per second at table %(table)s",
                        {'rate': self.conf.dnat_ttl_invalid_max_rate,
                         'table': const.EGRESS_DNAT_TABLE})
            return

        msg = event.msg

        pkt = packet.Packet(msg.data)
        e_pkt = pkt.get_protocol(ethernet.ethernet)
        port_key = msg.match.get('reg6')
        floatingip = self.fip_port_key_cache.get(port_key)
        if floatingip is None:
            LOG.warning("The invalid TTL packet's destination mac %s "
                        "can't be recognized.", e_pkt.src)
            return

        icmp_ttl_pkt = icmp_error_generator.generate(
            icmp.ICMP_TIME_EXCEEDED, icmp.ICMP_TTL_EXPIRED_CODE,
            msg.data, floatingip.floating_ip_address, pkt)
        self.dispatch_packet(icmp_ttl_pkt, port_key)

    def _handle_egress_icmp_translate(self, event):
        if self.ingress_icmp_error_rate_limit():
            LOG.warning("Get more than %(rate)s ICMP error messages "
                        "per second at table %(table)s",
                        {'rate': self.conf.dnat_icmp_error_max_rate,
                         'table': const.INGRESS_DNAT_TABLE})
            return

        msg = event.msg

        pkt = packet.Packet(msg.data)

        reply_pkt = self._revert_nat_for_icmp_embedded_packet(pkt, EGRESS)
        metadata = msg.match.get('metadata')

        self.reinject_packet(
            reply_pkt,
            table_id=const.L2_LOOKUP_TABLE,
            actions=[self.parser.OFPActionSetField(metadata=metadata)]
        )

    def egress_packet_in_handler(self, event):
        if event.msg.reason == self.ofproto.OFPR_INVALID_TTL:
            self._handle_egress_invalid_ttl(event)
        else:
            self._handle_egress_icmp_translate(event)

    def _revert_nat_for_icmp_embedded_packet(self, pkt, direction):
        e_pkt = pkt.get_protocol(ethernet.ethernet)
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)
        ipv4_pkt.csum = 0
        icmp_pkt = pkt.get_protocol(icmp.icmp)

        embeded_ipv4_pkt, _, payload = ipv4.ipv4.parser(icmp_pkt.data.data)
        if direction == EGRESS:
            embeded_ipv4_pkt.dst = ipv4_pkt.src
        else:
            embeded_ipv4_pkt.src = ipv4_pkt.dst
        embeded_data = embeded_ipv4_pkt.serialize(None, None) + payload
        icmp_pkt.data.data = embeded_data
        # Re-calculate when encoding
        icmp_pkt.csum = 0

        reply_pkt = packet.Packet()
        reply_pkt.add_protocol(e_pkt)
        reply_pkt.add_protocol(ipv4_pkt)
        reply_pkt.add_protocol(icmp_pkt)
        return reply_pkt

    def _get_vm_port_info(self, floatingip):
        lport = floatingip.lport
        mac = lport.mac
        ip = lport.ip
        tunnel_key = lport.unique_key
        local_network_id = lport.lswitch.unique_key

        return mac, ip, tunnel_key, local_network_id

    def _get_vm_gateway_info(self, floatingip):
        lport = floatingip.lport
        lrouter = floatingip.lrouter
        for router_port in lrouter.ports:
            if router_port.lswitch.id == lport.lswitch.id:
                return router_port.mac
        return None

    def _get_arp_responder(self, floatingip):
        # ARP responder is placed in L2. This is needed to avoid the multicast
        # flow for provider network in L2 table.
        # The packet is egressed to EGRESS_TABLE so it can reach the provide
        # network.
        return arp_responder.ArpResponder(
            app=self,
            network_id=floatingip.floating_lport.lswitch.unique_key,
            interface_ip=floatingip.floating_lport.ip,
            interface_mac=floatingip.floating_lport.mac,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            goto_table_id=const.EGRESS_TABLE,
        )

    def _get_ingress_nat_actions(self, floatingip):
        vm_gateway_mac = self._get_vm_gateway_info(floatingip)
        if vm_gateway_mac is None:
            vm_gateway_mac = floatingip.floating_lport.mac

        return [
            self.parser.OFPActionDecNwTtl(),
            self.parser.OFPActionSetField(eth_src=vm_gateway_mac),
            self.parser.OFPActionSetField(eth_dst=floatingip.lport.mac),
            self.parser.OFPActionSetField(ipv4_dst=floatingip.lport.ip),
            self.parser.OFPActionSetField(reg7=floatingip.lport.unique_key),
            self.parser.OFPActionSetField(
                metadata=floatingip.lport.lswitch.unique_key),
        ]

    def _install_ingress_nat_flows(self, floatingip):
        parser = self.parser
        ofproto = self.ofproto

        self._get_arp_responder(floatingip).add()

        # Capture flow:
        # Each packet bound for a floating port is forwarded to DNAT table
        # This is done so we can be the handler for any PACKET_INs there
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=parser.OFPMatch(
                reg7=floatingip.floating_lport.unique_key,
                eth_type=ether.ETH_TYPE_IP,
            ),
            inst=[
                parser.OFPInstructionGotoTable(const.INGRESS_DNAT_TABLE),
            ],
        )

        # Translate flow
        self.mod_flow(
            table_id=const.INGRESS_DNAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=parser.OFPMatch(
                reg7=floatingip.floating_lport.unique_key,
                eth_type=ether.ETH_TYPE_IP,
            ),
            actions=self._get_ingress_nat_actions(floatingip) + [
                parser.NXActionResubmitTable(
                    table_id=const.L2_LOOKUP_TABLE),
            ],
        )

        # Add flows to packet-in icmp time exceed and icmp unreachable message
        for icmp_type in (icmp.ICMP_DEST_UNREACH, icmp.ICMP_TIME_EXCEEDED):
            self.mod_flow(
                table_id=const.INGRESS_DNAT_TABLE,
                priority=const.PRIORITY_HIGH,
                match=parser.OFPMatch(
                    reg7=floatingip.floating_lport.unique_key,
                    eth_type=ether.ETH_TYPE_IP,
                    ip_proto=in_proto.IPPROTO_ICMP,
                    icmpv4_type=icmp_type,
                ),
                actions=self._get_ingress_nat_actions(floatingip) + [
                    parser.OFPActionOutput(
                        ofproto.OFPP_CONTROLLER,
                        ofproto.OFPCML_NO_BUFFER,
                    ),
                ],
            )

    def _remove_ingress_nat_rules(self, floatingip):
        self._get_arp_responder(floatingip).remove()

        # Remove capture rule
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_TABLE,
            match=self.parser.OFPMatch(
                reg7=floatingip.floating_lport.unique_key,
            ),
        )

        # Remove translate + ICMP rules
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE,
            table_id=const.INGRESS_DNAT_TABLE,
            match=self.parser.OFPMatch(
                reg7=floatingip.floating_lport.unique_key,
            ),
        )

    def _get_dnat_egress_match(self, floatingip, **kwargs):
        return self.parser.OFPMatch(
            metadata=floatingip.lport.lswitch.unique_key,
            reg6=floatingip.lport.unique_key,
            reg5=floatingip.lrouter.unique_key,
            eth_type=ether.ETH_TYPE_IP,
            ipv4_src=floatingip.lport.ip,
            **kwargs
        )

    def _get_external_subnet(self, fip):
        subnets = fip.floating_lport.lswitch.subnets
        for subnet in subnets:
            if fip.floating_ip_address in subnet.cidr:
                return subnet

    def _get_external_cidr(self, fip):
        return self._get_external_subnet(fip).cidr

    def _get_egress_nat_actions(self, floatingip):
        parser = self.parser

        return [
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(eth_src=floatingip.floating_lport.mac),
            parser.OFPActionSetField(eth_dst=const.EMPTY_MAC),
            parser.OFPActionSetField(ipv4_src=floatingip.floating_ip_address),
            parser.OFPActionSetField(
                metadata=floatingip.floating_lport.lswitch.unique_key),
            parser.OFPActionSetField(reg6=floatingip.floating_lport.unique_key)
        ]

    def _install_egress_nat_rules(self, floatingip):
        if self._get_external_cidr(floatingip).version != n_const.IP_VERSION_4:
            return

        parser = self.parser
        ofproto = self.ofproto

        # Capture flow: relevant packets in L3 go to EGRESS_DNAT
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_LOW,
            match=self._get_dnat_egress_match(floatingip),
            inst=[
                parser.OFPInstructionGotoTable(const.EGRESS_DNAT_TABLE)
            ],
        )

        self.mod_flow(
            table_id=const.EGRESS_DNAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self._get_dnat_egress_match(floatingip),
            actions=self._get_egress_nat_actions(floatingip) + [
                parser.NXActionResubmitTable(
                    table_id=const.L2_LOOKUP_TABLE,
                )
            ],
        )

        # Add flows to packet-in icmp time exceed and icmp unreachable message
        for icmp_type in (icmp.ICMP_DEST_UNREACH, icmp.ICMP_TIME_EXCEEDED):
            self.mod_flow(
                table_id=const.EGRESS_DNAT_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self._get_dnat_egress_match(
                    floatingip,
                    ip_proto=in_proto.IPPROTO_ICMP,
                    icmpv4_type=icmp_type,
                ),
                actions=self._get_egress_nat_actions(floatingip) + [
                    parser.OFPActionOutput(
                        ofproto.OFPP_CONTROLLER,
                        ofproto.OFPCML_NO_BUFFER,
                    ),
                ],
            )

    def _remove_egress_nat_rules(self, floatingip):
        if self._get_external_cidr(floatingip).version != n_const.IP_VERSION_4:
            return

        # Capture flow
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE,
            table_id=const.L3_LOOKUP_TABLE,
            match=self._get_dnat_egress_match(floatingip)
        )

        # Translate + ICMP
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_DNAT_TABLE,
            match=self._get_dnat_egress_match(floatingip)
        )

    def update_floatingip_status(self, floatingip, status):
        if self.neutron_server_notifier:
            self.neutron_server_notifier.notify_fip_status(floatingip, status)

    @df_base_app.register_event(l3.FloatingIp, model_constants.EVENT_CREATED)
    def _create_floatingip(self, fip):
        if fip.is_local:
            self._associate_floatingip(fip)
            self.update_floatingip_status(
                fip, n_const.FLOATINGIP_STATUS_ACTIVE)

    @df_base_app.register_event(l3.FloatingIp, model_constants.EVENT_UPDATED)
    def _update_floatingip(self, fip, original_fip):
        if original_fip.lport == fip.lport:
            return

        if original_fip.is_local:
            self._disassociate_floatingip(original_fip)

        if fip.is_local:
            self._associate_floatingip(fip)

        old_status = _fip_status_by_lport(original_fip)
        new_status = _fip_status_by_lport(fip)

        # FIXME (dimak): Race here: we should only update on disassociate
        # or reassociate when FIP is still local
        if old_status != new_status:
            self.update_floatingip_status(fip, new_status)

    def _associate_floatingip(self, floatingip):
        self.local_floatingips[floatingip.id] = floatingip
        lport = floatingip.lport
        self.fip_port_key_cache[lport.unique_key] = floatingip
        self._install_ingress_nat_flows(floatingip)
        self._install_egress_nat_rules(floatingip)

    def _disassociate_floatingip(self, floatingip):
        self.local_floatingips.pop(floatingip.id, 0)
        lport = floatingip.lport
        self.fip_port_key_cache.pop(lport.unique_key, None)
        self._remove_ingress_nat_rules(floatingip)
        self._remove_egress_nat_rules(floatingip)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_UPDATED)
    def _update_local_port(self, lport, orig_lport=None):
        if orig_lport is not None and orig_lport.is_local:
            # Associate only when lport becomes local
            return

        fips = self.db_store.get_all(
            l3.FloatingIp(lport=lport),
            index=l3.FloatingIp.get_index('lport'),
        )

        for fip in fips:
            self._associate_floatingip(fip)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _remove_local_port(self, lport):
        ips_to_disassociate = (
            fip for fip in self.local_floatingips.values()
            if fip.lport.id == lport.id)
        for floatingip in ips_to_disassociate:
            self._disassociate_floatingip(floatingip)
            self.update_floatingip_status(
                floatingip, n_const.FLOATINGIP_STATUS_DOWN)

    @df_base_app.register_event(l3.FloatingIp, model_constants.EVENT_DELETED)
    def _delete_floatingip(self, floatingip):
        if floatingip.is_local:
            self._disassociate_floatingip(floatingip)
