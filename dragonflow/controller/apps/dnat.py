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
from dragonflow.controller import port_locator
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import l3


LOG = log.getLogger(__name__)

EGRESS = 'egress'

INGRESS = 'ingress'


class DNATApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(DNATApp, self).__init__(*args, **kwargs)
        self.conf = cfg.CONF.df_dnat_app
        # Map between fixed ip mac to floating ip
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
        lport = self.db_store.get_one(
            l2.LogicalPort(unique_key=port_key),
            index=l2.LogicalPort.get_index('unique_key'),
        )
        floatingip = self.db_store.get_one(
            l3.FloatingIp(lport=lport.id),
            index=l3.FloatingIp.get_index('lport'),
        )
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

    def _get_vm_gateway_mac(self, floatingip):
        lport = floatingip.lport
        lrouter = floatingip.lrouter
        for router_port in lrouter.ports:
            if router_port.lswitch.id == lport.lswitch.id:
                return router_port.mac
        return None

    def _get_arp_responder(self, floatingip):
        # ARP responder is placed in L2. This is needed to avoid the multicast
        # flow for provider network in L2 table.
        # The packet is egressed to EGRESS_TABLE so it can reach the provider
        # network.
        return arp_responder.ArpResponder(
            app=self,
            network_id=floatingip.floating_lport.lswitch.unique_key,
            interface_ip=floatingip.floating_lport.ip,
            interface_mac=floatingip.floating_lport.mac,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            goto_table_id=const.EGRESS_TABLE,
            source_port_key=floatingip.floating_lport.unique_key,
        )

    def _get_ingress_nat_actions(self, floatingip):
        vm_gateway_mac = self._get_vm_gateway_mac(floatingip)
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

    def _get_dnat_ingress_match(self, floatingip, **kwargs):
        return self.parser.OFPMatch(
            reg7=floatingip.floating_lport.unique_key,
            **kwargs
        )

    def _install_ingress_capture_flow(self, floatingip):
        # Capture flow:
        # Each packet bound for a floating port is forwarded to DNAT table
        # This is done so we can be the handler for any PACKET_INs there
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_HIGH,
            match=self._get_dnat_ingress_match(floatingip),
            inst=[
                self.parser.OFPInstructionGotoTable(const.INGRESS_DNAT_TABLE),
            ],
        )

    def _uninstall_ingress_capture_flow(self, floatingip):
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_HIGH,
            match=self._get_dnat_ingress_match(floatingip),
        )

    def _install_ingress_translate_flow(self, floatingip):
        self.mod_flow(
            table_id=const.INGRESS_DNAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self._get_dnat_ingress_match(
                floatingip,
                eth_type=ether.ETH_TYPE_IP,
            ),
            actions=self._get_ingress_nat_actions(floatingip) + [
                self.parser.NXActionResubmitTable(
                    table_id=const.L2_LOOKUP_TABLE),
            ],
        )

    def _uninstall_ingress_translate_flow(self, floatingip):
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_DNAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self._get_dnat_ingress_match(
                floatingip,
                eth_type=ether.ETH_TYPE_IP,
            ),
        )

    def _get_ingress_icmp_flow_match(self, floatingip, icmp_type):
        return self._get_dnat_ingress_match(
            floatingip,
            eth_type=ether.ETH_TYPE_IP,
            ip_proto=in_proto.IPPROTO_ICMP,
            icmpv4_type=icmp_type,
        )

    def _install_ingress_icmp_flows(self, floatingip):
        # Translate flow
        # Add flows to packet-in icmp time exceed and icmp unreachable message
        for icmp_type in (icmp.ICMP_DEST_UNREACH, icmp.ICMP_TIME_EXCEEDED):
            self.mod_flow(
                table_id=const.INGRESS_DNAT_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self._get_ingress_icmp_flow_match(floatingip, icmp_type),
                actions=self._get_ingress_nat_actions(floatingip) + [
                    self.parser.OFPActionOutput(
                        self.ofproto.OFPP_CONTROLLER,
                        self.ofproto.OFPCML_NO_BUFFER,
                    ),
                ],
            )

    def _uninstall_ingress_icmp_flows(self, floatingip):
        for icmp_type in (icmp.ICMP_DEST_UNREACH, icmp.ICMP_TIME_EXCEEDED):
            self.mod_flow(
                command=self.ofproto.OFPFC_DELETE_STRICT,
                table_id=const.INGRESS_DNAT_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self._get_ingress_icmp_flow_match(floatingip, icmp_type),
            )

    def _install_ingress_nat_flows(self, floatingip):
        self._get_arp_responder(floatingip).add()
        self._install_ingress_capture_flow(floatingip)
        self._install_ingress_translate_flow(floatingip)
        self._install_ingress_icmp_flows(floatingip)

    def _remove_ingress_nat_rules(self, floatingip):
        self._get_arp_responder(floatingip).remove()
        self._uninstall_ingress_capture_flow(floatingip)
        self._uninstall_ingress_translate_flow(floatingip)
        self._uninstall_ingress_icmp_flows(floatingip)

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

    def _install_egress_capture_flow(self, floatingip):
        # Capture flow: relevant packets in L3 go to EGRESS_DNAT
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM_LOW,
            match=self._get_dnat_egress_match(floatingip),
            inst=[
                self.parser.OFPInstructionGotoTable(const.EGRESS_DNAT_TABLE)
            ],
        )

    def _uninstall_egress_capture_flow(self, floatingip):
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM_LOW,
            match=self._get_dnat_egress_match(floatingip),
        )

    def _install_egress_translate_flow(self, floatingip):
        self.mod_flow(
            table_id=const.EGRESS_DNAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self._get_dnat_egress_match(floatingip),
            actions=self._get_egress_nat_actions(floatingip) + [
                self.parser.NXActionResubmitTable(
                    table_id=const.L2_LOOKUP_TABLE,
                )
            ],
        )

    def _uninstall_egress_translate_flow(self, floatingip):
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_DNAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self._get_dnat_egress_match(floatingip),
        )

    def _install_egress_icmp_flows(self, floatingip):
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
                    self.parser.OFPActionOutput(
                        self.ofproto.OFPP_CONTROLLER,
                        self.ofproto.OFPCML_NO_BUFFER,
                    ),
                ],
            )

    def _uninstall_egress_icmp_flows(self, floatingip):
        for icmp_type in (icmp.ICMP_DEST_UNREACH, icmp.ICMP_TIME_EXCEEDED):
            self.mod_flow(
                command=self.ofproto.OFPFC_DELETE_STRICT,
                table_id=const.EGRESS_DNAT_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self._get_dnat_egress_match(
                    floatingip,
                    ip_proto=in_proto.IPPROTO_ICMP,
                    icmpv4_type=icmp_type,
                ),
            )

    def _install_egress_nat_rules(self, floatingip):
        self._install_egress_capture_flow(floatingip)
        self._install_egress_translate_flow(floatingip)
        self._install_egress_icmp_flows(floatingip)

    def _remove_egress_nat_rules(self, floatingip):
        self._uninstall_egress_capture_flow(floatingip)
        self._uninstall_egress_translate_flow(floatingip)
        self._uninstall_egress_icmp_flows(floatingip)

    @df_base_app.register_event(l3.FloatingIp, model_constants.EVENT_CREATED)
    def _create_floatingip(self, floatingip):
        if floatingip.lport is not None:
            self._install_floatingip(floatingip)

    @df_base_app.register_event(l3.FloatingIp, model_constants.EVENT_UPDATED)
    def _update_floatingip(self, floatingip, orig_floatingip):
        if orig_floatingip.lport == floatingip.lport:
            return

        if orig_floatingip.lport is not None:
            # Update here only if we're disassociating
            self._uninstall_floatingip(orig_floatingip)

        if floatingip.lport is not None:
            # Update here only if we're associating
            self._install_floatingip(floatingip)

    @df_base_app.register_event(l3.FloatingIp, model_constants.EVENT_DELETED)
    def _delete_floatingip(self, floatingip):
        if floatingip.lport is None:
            return

        # FIXME lport in self.db_store
        if floatingip.floating_lport.get_object() is None:
            return

        self._uninstall_floatingip(floatingip)

    def _install_floatingip(self, floatingip):
        if floatingip.lport.is_local:
            self._install_local_floatingip(floatingip)
        elif floatingip.lport.is_remote:
            self._install_remote_floatingip(floatingip)

    def _uninstall_floatingip(self, floatingip):
        if floatingip.lport.is_local:
            self._uninstall_local_floatingip(floatingip)
        elif floatingip.lport.is_remote:
            self._uninstall_remote_floatingip(floatingip)

    def _install_local_floatingip(self, floatingip):
        if self._get_external_cidr(floatingip).version != n_const.IP_VERSION_4:
            return

        self._install_ingress_nat_flows(floatingip)
        self._install_egress_nat_rules(floatingip)

        port_locator.copy_port_binding(
            floatingip.floating_lport,
            floatingip.lport,
        )
        floatingip.floating_lport.emit_bind_local()

    def _uninstall_local_floatingip(self, floatingip, emit_unbind=True):
        if self._get_external_cidr(floatingip).version != n_const.IP_VERSION_4:
            return

        port_locator.clear_port_binding(floatingip.floating_lport)
        if emit_unbind:
            floatingip.floating_lport.emit_unbind_local()

        self._remove_ingress_nat_rules(floatingip)
        self._remove_egress_nat_rules(floatingip)

    def _install_remote_floatingip(self, floatingip):
        port_locator.copy_port_binding(
            floatingip.floating_lport, floatingip.lport)

        floatingip.floating_lport.emit_bind_remote()

    def _uninstall_remote_floatingip(self, floatingip, emit_unbind=True):
        port_locator.clear_port_binding(floatingip.floating_lport)
        if emit_unbind:
            floatingip.floating_lport.emit_unbind_remote()

    def _get_floatingips_by_lport(self, lport):
        return self.db_store.get_all(
            l3.FloatingIp(lport=lport.id),
            index=l3.FloatingIp.get_index('lport'),
        )

    def _get_floatingips_by_floating_lport(self, lport):
        return self.db_store.get_all(
            l3.FloatingIp(floating_lport=lport.id),
            index=l3.FloatingIp.get_index('floating_lport'),
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _local_port_bound(self, lport):
        for floatingip in self._get_floatingips_by_lport(lport):
            self._install_local_floatingip(floatingip)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _local_port_unbound(self, lport):
        for floatingip in self._get_floatingips_by_lport(lport):
            self._uninstall_local_floatingip(floatingip)

        for floatingip in self._get_floatingips_by_floating_lport(lport):
            self._uninstall_local_floatingip(floatingip, emit_unbind=False)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_REMOTE)
    def _remote_port_bound(self, lport):
        for floatingip in self._get_floatingips_by_lport(lport):
            self._install_remote_floatingip(floatingip)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_REMOTE)
    def _remote_port_unbound(self, lport):
        for floatingip in self._get_floatingips_by_lport(lport):
            self._uninstall_remote_floatingip(floatingip)

        for floatingip in self._get_floatingips_by_floating_lport(lport):
            self._uninstall_remote_floatingip(floatingip, emit_unbind=False)
