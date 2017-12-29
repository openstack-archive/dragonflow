# Copyright (c) 2018 OpenStack Foundation.
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
from ryu.lib.packet import tcp
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


class PATApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(PATApp, self).__init__(*args, **kwargs)
        self.conf = cfg.CONF.df_dnat_app
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
        self.api.register_table_handler(const.INGRESS_PAT_TABLE,
                                        self.ingress_packet_in_handler)
        self.api.register_table_handler(const.EGRESS_PAT_TABLE,
                                        self.egress_packet_in_handler)

    def _handle_ingress_invalid_ttl(self, event):
        if self.ingress_ttl_invalid_handler_rate_limit():
            LOG.warning("Get more than %(rate)s TTL invalid "
                        "packets per second at table %(table)s",
                        {'rate': self.conf.dnat_ttl_invalid_max_rate,
                         'table': const.INGRESS_PAT_TABLE})
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
        #TODO(pino): finish this implementation
        return
        '''
        if self.ingress_icmp_error_rate_limit():
            LOG.warning("Get more than %(rate)s ICMP error messages "
                        "per second at table %(table)s",
                        {'rate': self.conf.dnat_icmp_error_max_rate,
                         'table': const.INGRESS_PAT_TABLE})
            return

        msg = event.msg
        pkt = packet.Packet(msg.data)
        e_pkt = pkt.get_protocol(ethernet.ethernet)
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)
        ipv4_pkt.csum = 0
        icmp_pkt = pkt.get_protocol(icmp.icmp)
        embeded_ipv4_pkt, _, payload = ipv4.ipv4.parser(icmp_pkt.data.data)
        embeded_tcp_pkt = embeded_ipv4_pkt.get_protocol(tcp.tcp)
        pat_l4_port = embeded_tcp_pkt.src_port
        pat_lport = self.db_store.get_one(
            l2.LogicalPort(unique_key=msg.match.get('reg7')),
            index=l2.LogicalPort.get_index('unique_key'),
        )
        pat = self.db_store.get_one(
            l3.PAT(lport=pat_lport.id),
            index=l3.PAT.get_index('lport'),
        )
        if pat is None:
            LOG.warning("PAT not found for ingress ICMP error.")
            return
        # TODO(pino): index by pat and L4 port
        pat_entry = None
        for e in self._get_pat_entries_by_pat(pat):
            if e.pat_l4_port is pat_l4_port:
                pat_entry = e
                break
        if pat is None:
            LOG.warning("PATEntry not found for ingress ICMP error.")
            return
        embeded_ipv4_pkt.dst = None
        embeded_tcp_pkt.src_port = None

        embeded_data = embeded_ipv4_pkt.serialize(None, None) + payload
        icmp_pkt.data.data = embeded_data
        # Re-calculate when encoding
        icmp_pkt.csum = 0

        reply_pkt = packet.Packet()
        reply_pkt.add_protocol(e_pkt)
        reply_pkt.add_protocol(ipv4_pkt)
        reply_pkt.add_protocol(icmp_pkt)
        port_key = msg.match.get('reg7')
        self.dispatch_packet(reply_pkt, port_key)
        '''

    def ingress_packet_in_handler(self, event):
        LOG.debug("Ingress PAT table packet-in event {}".format(event))
        if event.msg.reason == self.ofproto.OFPR_INVALID_TTL:
            self._handle_ingress_invalid_ttl(event)
        else:
            self._handle_ingress_icmp_translate(event)

    def egress_packet_in_handler(self, event):
        LOG.debug("Egress PAT table packet-in event {}".format(event))
        # TODO(pino): implement this
        return

    def _get_vm_gateway_mac(self, pat_entry):
        for router_port in pat_entry.lrouter.ports:
            if router_port.lswitch.id == pat_entry.lport.lswitch.id:
                return router_port.mac
        return None

    def _icmp_echo_match(self, pat):
        return self.parser.OFPMatch(
            reg7=pat.lport.unique_key,
            eth_type=ether.ETH_TYPE_IP,
            ip_proto=in_proto.IPPROTO_ICMP,
            ipv4_dst=pat.ip_address,
            icmpv4_type = icmp.ICMP_ECHO_REQUEST,
        )

    def _add_icmp_echo_responder(self, pat):
        parser = self.parser
        actions = [
            parser.OFPActionSetNwTtl(64),
            parser.OFPActionSetField(eth_dst=const.EMPTY_MAC),
            parser.OFPActionSetField(eth_src=pat.lport.mac),
            parser.NXActionRegMove(src_field='ipv4_src',
                                   dst_field='ipv4_dst',
                                   n_bits=32),
            parser.OFPActionSetField(ipv4_src=pat.ip_address),
            parser.OFPActionSetField(icmpv4_type=icmp.ICMP_ECHO_REPLY),
            parser.OFPActionSetField(metadata=pat.lport.lswitch.unique_key),
            parser.OFPActionSetField(reg6=pat.lport.unique_key),
            parser.OFPActionSetField(reg7=0),
            parser.NXActionResubmitTable(table_id=const.L2_LOOKUP_TABLE),
        ]
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=self._icmp_echo_match(pat),
            actions=actions,
        )

    def _remove_icmp_echo_responder(self, pat):
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=self._icmp_echo_match(pat),
        )

    def _get_arp_responder(self, pat):
        # ARP responder is placed in L2. This is needed to avoid the multicast
        # flow for provider network in L2 table.
        # The packet is egressed to EGRESS_TABLE so it can reach the provider
        # network.
        return arp_responder.ArpResponder(
            app=self,
            network_id=pat.lport.lswitch.unique_key,
            interface_ip=pat.ip_address,
            interface_mac=pat.lport.mac,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            goto_table_id=const.EGRESS_TABLE,
            source_port_key=pat.lport.unique_key,
        )

    def _get_ingress_nat_actions(self, pat_entry):
        vm_gateway_mac = self._get_vm_gateway_mac(pat_entry)
        if vm_gateway_mac is None:
            vm_gateway_mac = pat_entry.pat.lport.mac

        return [
            self.parser.OFPActionDecNwTtl(),
            self.parser.OFPActionSetField(eth_src=vm_gateway_mac),
            self.parser.OFPActionSetField(eth_dst=pat_entry.lport.mac),
            self.parser.OFPActionSetField(ipv4_dst=pat_entry.fixed_ip_address),
            self.parser.OFPActionSetField(tcp_dst=pat_entry.fixed_l4_port),
            self.parser.OFPActionSetField(reg7=pat_entry.lport.unique_key),
            self.parser.OFPActionSetField(
                metadata=pat_entry.lport.lswitch.unique_key),
        ]

    def _get_pat_ingress_match(self, pat, **kwargs):
        return self.parser.OFPMatch(
            reg7=pat.lport.unique_key,
            **kwargs
        )

    def _get_pat_entry_ingress_match(self, pat_entry, **kwargs):
        return self.parser.OFPMatch(
            reg7=pat_entry.pat.lport.unique_key,
            eth_type=ether.ETH_TYPE_IP,
            ip_proto=n_const.PROTO_NUM_TCP,
            tcp_dst=pat_entry.pat_l4_port,
            **kwargs
        )

    def _get_egress_match(self, pat_entry, **kwargs):
        return self.parser.OFPMatch(
            metadata=pat_entry.lport.lswitch.unique_key,
            reg6=pat_entry.lport.unique_key,
            reg5=pat_entry.lrouter.unique_key,
            eth_type=ether.ETH_TYPE_IP,
            ipv4_src=pat_entry.fixed_ip_address,
            ip_proto=n_const.PROTO_NUM_TCP,
            tcp_src=pat_entry.fixed_l4_port,
            **kwargs
        )

    def _get_egress_nat_actions(self, pat_entry):
        parser = self.parser

        return [
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(eth_src=pat_entry.pat.lport.mac),
            parser.OFPActionSetField(eth_dst=const.EMPTY_MAC),
            parser.OFPActionSetField(ipv4_src=pat_entry.pat.ip_address),
            parser.OFPActionSetField(tcp_src=pat_entry.pat_l4_port),
            parser.OFPActionSetField(
                metadata=pat_entry.pat.lport.lswitch.unique_key),
            parser.OFPActionSetField(reg6=pat_entry.pat.lport.unique_key)
        ]

    def _get_ingress_icmp_flow_match(self, pat, icmp_type):
        return self.parser.OFPMatch(
            reg7=pat.lport.unique_key,
            eth_type=ether.ETH_TYPE_IP,
            ip_proto=in_proto.IPPROTO_ICMP,
            icmpv4_type=icmp_type,
        )

    def _install_ingress_icmp_flows(self, pat):
        # Translate flow
        # Add flows to packet-in icmp time exceed and icmp unreachable message
        for icmp_type in (icmp.ICMP_DEST_UNREACH, icmp.ICMP_TIME_EXCEEDED):
            self.mod_flow(
                table_id=const.INGRESS_PAT_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self._get_ingress_icmp_flow_match(pat, icmp_type),
                actions= [
                    self.parser.OFPActionOutput(
                        self.ofproto.OFPP_CONTROLLER,
                        self.ofproto.OFPCML_NO_BUFFER,
                    ),
                ],
            )

    def _uninstall_ingress_icmp_flows(self, pat):
        for icmp_type in (icmp.ICMP_DEST_UNREACH, icmp.ICMP_TIME_EXCEEDED):
            self.mod_flow(
                command=self.ofproto.OFPFC_DELETE_STRICT,
                table_id=const.INGRESS_PAT_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self._get_ingress_icmp_flow_match(pat, icmp_type),
            )

    def _install_pat_ingress_flows(self, pat):
        match = self._get_pat_ingress_match(pat)
        arp = self._get_arp_responder(pat)
        arp.add()
        LOG.debug('install ingress flows for PAT {} with match {} and ARP '
                  '{}'.format(pat, match, arp))
        self._add_icmp_echo_responder(pat)
        self._install_ingress_icmp_flows(pat)
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match,
            inst=[
                self.parser.OFPInstructionGotoTable(const.INGRESS_PAT_TABLE),
            ],
        )

    def _uninstall_pat_ingress_flows(self, pat):
        LOG.debug('uninstall ingress flows for PAT {}'.format(pat))
        self._get_arp_responder(pat).remove()
        self._remove_icmp_echo_responder(pat)
        self._uninstall_ingress_icmp_flows(pat)
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_HIGH,
            match=self._get_pat_ingress_match(pat),
        )

    def _install_pat_entry_ingress_flows(self, pat_entry):
        match = self._get_pat_entry_ingress_match(pat_entry)
        nat_actions = self._get_ingress_nat_actions(pat_entry) + [
                self.parser.NXActionResubmitTable(
                    table_id=const.L2_LOOKUP_TABLE)]
        LOG.debug('install ingress flows for PATEntry {} with match {} '
                  'and translation {}'.format(pat_entry,
                                              match,
                                              nat_actions))
        self.mod_flow(
            table_id=const.INGRESS_PAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            actions=nat_actions,
        )

    def _uninstall_pat_entry_ingress_flows(self, pat_entry):
        LOG.debug('uninstall ingress flows for PATEntry {}'.format(pat_entry))
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_PAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self._get_pat_entry_ingress_match(pat_entry),
        )

    def _install_egress_flows(self, pat_entry):
        match = self._get_egress_match(pat_entry)
        nat_actions = self._get_egress_nat_actions(pat_entry) + [
                self.parser.NXActionResubmitTable(
                    table_id=const.L2_LOOKUP_TABLE)]
        LOG.debug('install egress flows for PATEntry {} with match {} '
                  'and translation {}'.format(pat_entry,
                                              match,
                                              nat_actions))
        self.mod_flow(
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match,
            inst=[
                self.parser.OFPInstructionGotoTable(const.EGRESS_PAT_TABLE)
            ],
        )
        self.mod_flow(
            table_id=const.EGRESS_PAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            actions=nat_actions,
        )

    def _uninstall_egress_flows(self, pat_entry):
        LOG.debug('uninstall egress flows for PATEntry {}'.format(pat_entry))
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=self._get_egress_match(pat_entry),
        )
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_PAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self._get_egress_match(pat_entry),
        )

    def _get_pats_by_lport(self, lport):
        return self.db_store.get_all(
            l3.PAT(lport=lport.id),
            index=l3.PAT.get_index('lport'),
        )

    def _get_pat_entries_by_pat(self, pat):
        return self.db_store.get_all(
            l3.PATEntry(pat=pat.id),
            index=l3.PATEntry.get_index('pat'),
        )

    def _get_pat_entries_by_lport(self, lport):
        return self.db_store.get_all(
            l3.PATEntry(lport=lport.id),
            index=l3.PATEntry.get_index('lport'),
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _local_port_bound(self, lport):
        for pat_entry in self._get_pat_entries_by_lport(lport):
            LOG.debug('Locally bound port is used by PATEntry '
                      '{}'.format(pat_entry))
            self._install_egress_flows(pat_entry)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _local_port_unbound(self, lport):
        for pat_entry in self._get_pat_entries_by_lport(lport):
            LOG.debug('Locally unbound port is used by PATEntry '
                      '{}'.format(pat_entry))
            self._uninstall_egress_flows(pat_entry)

    @df_base_app.register_event(l3.PAT, model_constants.EVENT_CREATED)
    def _create_pat(self, pat):
        if pat.chassis is None: return
        LOG.debug('PAT {} was created or updated; creating binding for its '
                  'lport {}'.format(pat, pat.lport))
        binding = l2.PortBinding(type=l2.BINDING_CHASSIS,
                                 chassis=pat.chassis)
        port_locator.set_port_binding(pat.lport, binding)
        if binding.is_local:
            pat.lport.emit_bind_local()
            self._install_pat_ingress_flows(pat)
            for pat_entry in self._get_pat_entries_by_pat(pat):
                self._install_pat_entry_ingress_flows(pat_entry)
        else:
            pat.lport.emit_bind_remote()

        for pat_entry in self._get_pat_entries_by_pat(pat):
            if pat_entry.lport.is_local:
                self._install_egress_flows(pat_entry)

    @df_base_app.register_event(l3.PAT, model_constants.EVENT_UPDATED)
    def _update_pat(self, pat, orig_pat):
        self._delete_pat(orig_pat)
        self._create_pat(pat)

    @df_base_app.register_event(l3.PAT, model_constants.EVENT_DELETED)
    def _delete_pat(self, pat):
        if pat.chassis is None: return
        LOG.debug('PAT {} was created or updated; remove binding'.format(pat))
        was_local = pat.lport.is_local
        port_locator.clear_port_binding(pat.lport)
        if was_local:
            pat.lport.emit_unbind_local()
            self._uninstall_pat_ingress_flows(pat)
            for pat_entry in self._get_pat_entries_by_pat(pat):
                self._uninstall_pat_entry_ingress_flows(pat_entry)
        else:
            pat.lport.emit_unbind_remote()

        for pat_entry in self._get_pat_entries_by_pat(pat):
            if pat_entry.lport.is_local:
                self._uninstall_egress_flows(pat_entry)

    @df_base_app.register_event(l3.PATEntry, model_constants.EVENT_CREATED)
    def _create_pat_entry(self, pat_entry):
        if pat_entry.pat.chassis is None: return
        LOG.debug('Creating flows for PATEntry {}'.format(pat_entry))
        # Only the controller, C1, local to the PAT's port installs ingress
        # flows. This avoids having all controllers install flows for all PAT
        # entries (at the cost of all forward packets going through C1).
        if pat_entry.pat.lport.is_local:
            self._install_pat_entry_ingress_flows(pat_entry)
        # Only the controller, C2, local to the PAT entry's port installs
        # egress flows - return packets go direct without traversing C1.
        if pat_entry.lport.is_local:
            self._install_egress_flows(pat_entry)

    @df_base_app.register_event(l3.PATEntry, model_constants.EVENT_UPDATED)
    def _update_pat_entry(self, pat_entry, orig_pat_entry):
        self._delete_pat_entry(orig_pat_entry)
        self._create_pat_entry(pat_entry)

    @df_base_app.register_event(l3.PATEntry, model_constants.EVENT_DELETED)
    def _delete_pat_entry(self, pat_entry):
        if pat_entry.pat.chassis is None: return
        LOG.debug('Deleting flows for PATEntry {}'.format(pat_entry))
        if pat_entry.pat.lport.is_local:
            self._uninstall_pat_entry_ingress_flows(pat_entry)
        if pat_entry.lport.is_local:
            self._uninstall_egress_flows(pat_entry)
