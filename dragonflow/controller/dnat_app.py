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
import netaddr
import six

from dragonflow._i18n import _, _LE
from dragonflow.controller.common.arp_responder import ArpResponder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils
from dragonflow.controller.df_base_app import DFlowApp
from neutron.common import constants as n_const
from ryu.lib.packet import arp
from ryu.lib.packet import packet
from ryu.ofproto import ether

from oslo_config import cfg
from oslo_log import log
from oslo_service import loopingcall

LOG = log.getLogger(__name__)


DF_DNAT_APP_OPTS = [
    cfg.StrOpt('external_network_bridge',
              default='br-ex',
              help=_("Name of bridge used for external network traffic")),
    cfg.StrOpt('int_peer_patch_port', default='patch-ex',
               help=_("Peer patch port in integration bridge for external "
                      "bridge.")),
    cfg.StrOpt('ex_peer_patch_port', default='patch-int',
               help=_("Peer patch port in external bridge for integration "
                      "bridge.")),
    cfg.IntOpt('send_arp_interval', default=5,
               help=_("Polling interval for arp request in seconds"))
]

FIP_GW_RESOLVING_STATUS = 'resolving'


class DNATApp(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(DNATApp, self).__init__(*args, **kwargs)
        self.vswitch_api = kwargs['vswitch_api']
        self.nb_api = kwargs['nb_api']
        cfg.CONF.register_opts(DF_DNAT_APP_OPTS, group='df_dnat_app')
        self.external_network_bridge = \
            cfg.CONF.df_dnat_app.external_network_bridge
        self.int_peer_patch_port = cfg.CONF.df_dnat_app.int_peer_patch_port
        self.ex_peer_patch_port = cfg.CONF.df_dnat_app.ex_peer_patch_port
        self.send_arp_interval = cfg.CONF.df_dnat_app.send_arp_interval
        self.external_networks = collections.defaultdict(int)
        self.external_gateway_mac = collections.defaultdict(str)
        self.api.register_table_handler(const.INGRESS_NAT_TABLE,
                self.packet_in_handler)

    def switch_features_handler(self, ev):
        self._init_external_bridge()
        self._periodic_send_arp_request()

    def _get_external_gateway_mac(self, net_id):
        return self.external_gateway_mac[net_id]

    def _set_external_gateway_mac(self, net_id, gw_mac):
        self.external_gateway_mac[net_id] = gw_mac

    def _send_arp_request_entry(self):
        """Sending the arp request at the configured interval."""
        for net_id, gw_mac in six.iteritems(self.external_gateway_mac):
            fip = None
            # if gw mac is none, then need to get it
            if gw_mac is None:
                fip = self.db_store.get_first_floatingip(net_id)
            if fip:
                # request gw arp
                self._send_gw_arp_request(fip)

    def _periodic_send_arp_request(self):
        """Spawn a thread to periodically check the external gateway."""
        periodic = loopingcall.FixedIntervalLoopingCall(
            self._send_arp_request_entry)
        periodic.start(interval=self.send_arp_interval)

    def _init_external_bridge(self):
        self.external_ofport = self.vswitch_api.create_patch_port(
            const.DRAGONFLOW_DEFAULT_BRIDGE,
            self.ex_peer_patch_port,
            self.int_peer_patch_port)
        self.vswitch_api.create_patch_port(
            self.external_network_bridge,
            self.int_peer_patch_port,
            self.ex_peer_patch_port)

    def _update_external_gateway_mac(self, fips, learning_mac):
        net_id = fips[0].get_floating_network_id()
        gw_mac = self._get_external_gateway_mac(net_id)
        if not gw_mac or gw_mac != learning_mac:
            self._set_external_gateway_mac(net_id, learning_mac)
            for fip in fips:
                if fip.get_status() == FIP_GW_RESOLVING_STATUS:
                    self._install_dnat_egress_rules(fip)

    def packet_in_handler(self, event):
        msg = event.msg
        pkt = packet.Packet(msg.data)
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is None:
            LOG.error(_LE("No support for non ARP protocol"))
            return

        if (arp_pkt.opcode == arp.ARP_REQUEST and
            arp_pkt.src_ip == arp_pkt.dst_ip or
            arp_pkt.opcode == arp.ARP_REPLY):
            # learn gw mac from fip arp reply packet
            # or update gw mac from fip gateway gratuitous arp
            gw_fips = self.db_store.get_floatingips_by_gateway(arp_pkt.src_ip)
            if not gw_fips:
                return
            self._update_external_gateway_mac(gw_fips, arp_pkt.src_mac)

    def _send_gw_arp_request(self, fip):
        # TODO(Fei Rao)check the network type, snd the packet to external
        # gateway port
        self.send_arp_request(fip.get_mac_address(),
                              fip.get_ip_address(),
                              fip.get_external_gateway_ip(),
                              self.external_ofport)

    def _increase_external_network_count(self, network_id):
        self.external_networks[network_id] += 1

    def _decrease_external_network_count(self, network_id):
        self.external_networks[network_id] -= 1

    def _get_external_network_count(self, network_id):
        return self.external_networks[network_id]

    def _is_first_external_network(self, network_id):
        if self._get_external_network_count(network_id) == 0:
            # check whether there are other networks
            for key, val in six.iteritems(self.external_networks):
                if key != network_id and val > 0:
                    return False
            return True
        return False

    def _is_last_external_network(self, network_id):
        if self._get_external_network_count(network_id) == 1:
            # check whether there are other networks
            for key, val in six.iteritems(self.external_networks):
                if key != network_id and val > 0:
                    return False
            return True
        return False

    def _get_match_arp_reply(self, arp_tpa, arp_spa, network_id=None):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_tpa(utils.ipv4_text_to_int(str(arp_tpa)))
        match.set_arp_spa(utils.ipv4_text_to_int(str(arp_spa)))
        match.set_arp_opcode(arp.ARP_REPLY)
        if network_id is not None:
            match.set_metadata(network_id)
        return match

    def _get_match_gratuitous_arp(self, destination_ip, network_id=None):
        request_ip = utils.ipv4_text_to_int(str(destination_ip))
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_spa(request_ip)
        match.set_arp_tpa(request_ip)
        match.set_arp_opcode(arp.ARP_REQUEST)
        if network_id is not None:
            match.set_metadata(network_id)
        return match

    def _get_instructions_packet_in(self):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return inst

    def _install_mac_learning_rules(self, floatingip, ignore=False):
        # process arp reply
        match = self._get_match_arp_reply(
            floatingip.get_ip_address(),
            floatingip.get_external_gateway_ip())
        instructions = self._get_instructions_packet_in()
        self.mod_flow(
            self.get_datapath(),
            inst=instructions,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        network_id = floatingip.get_floating_network_id()
        if ignore or self._get_external_network_count(network_id) <= 0:
            # if it is the first floatingip for this external gateway,
            # install a gateway mac learning rules
            # process gratuitous arp
            match = self._get_match_gratuitous_arp(
                floatingip.get_external_gateway_ip())
            self.mod_flow(
                self.get_datapath(),
                inst=instructions,
                table_id=const.INGRESS_NAT_TABLE,
                priority=const.PRIORITY_MEDIUM,
                match=match)

    def _remove_mac_learning_rules(self, floatingip, ignore=False):
        ofproto = self.get_datapath().ofproto
        # remove arp reply rules
        match = self._get_match_arp_reply(
            floatingip.get_ip_address(),
            floatingip.get_external_gateway_ip())
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        network_id = floatingip.get_floating_network_id()
        if ignore or self._get_external_network_count(network_id) <= 1:
            # if it is the last flaotingip for this external gateway,
            # remove a gateway mac learning rules.
            # remove gratuitous arp rules
            match = self._get_match_gratuitous_arp(
                floatingip.get_external_gateway_ip())
            self.mod_flow(
                self.get_datapath(),
                command=ofproto.OFPFC_DELETE,
                table_id=const.INGRESS_NAT_TABLE,
                priority=const.PRIORITY_MEDIUM,
                match=match)

    def _install_floatingip_arp_responder(self, floatingip):
        # install floatingip arp responder flow rules
        if netaddr.IPAddress(floatingip.get_ip_address()).version != 4:
            return
        ArpResponder(self.get_datapath(),
             None,
             floatingip.get_ip_address(),
             floatingip.get_mac_address(),
             const.INGRESS_NAT_TABLE).add()

    def _remove_floatingip_arp_responder(self, floatingip):
        # install floatingip arp responder flow rules
        if netaddr.IPAddress(floatingip.get_ip_address()).version != 4:
            return
        ArpResponder(self.get_datapath(),
             None,
             floatingip.get_ip_address(),
             floatingip.get_mac_address(),
             const.INGRESS_NAT_TABLE).remove()

    def _get_vm_port_info(self, floatingip):
        lport = self.db_store.get_local_port(
            floatingip.get_lport_id())
        mac = lport.get_mac()
        ip = lport.get_ip()
        tunnel_key = lport.get_tunnel_key()
        network_id = lport.get_external_value('local_network_id')
        net_id = lport.get_lswitch_id()
        segmentation_id = self.db_store.get_network_id(
            net_id,
        )

        return (mac, ip, tunnel_key, network_id, segmentation_id)

    def _install_dnat_ingress_rules(self, floatingip):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ipv4_dst=floatingip.get_ip_address())

        vm_mac, vm_ip, vm_tunnel_key, network_id, _ = \
            self._get_vm_port_info(floatingip)
        fip_mac = floatingip.get_mac_address()
        actions = [
            parser.OFPActionSetField(eth_src=fip_mac),
            parser.OFPActionSetField(eth_dst=vm_mac),
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(ipv4_dst=vm_ip),
            parser.OFPActionSetField(reg7=vm_tunnel_key),
            parser.OFPActionSetField(metadata=network_id)
        ]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_CONNTRACK_TABLE)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_dnat_ingress_rules(self, floatingip):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ipv4_dst=floatingip.get_ip_address())
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _get_dnat_egress_match(self, floatingip):
        _, vm_ip, _, _, segmentation_id = self._get_vm_port_info(floatingip)
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                metadata=segmentation_id,
                                ipv4_src=vm_ip)
        return match

    def _install_dnat_egress_rules(self, floatingip):
        fip_mac = floatingip.get_mac_address()
        fip_ip = floatingip.get_ip_address()
        net_id = floatingip.get_floating_network_id()
        gw_mac = self._get_external_gateway_mac(net_id)
        if not gw_mac:
            # Record the resolving gw arp
            self._set_external_gateway_mac(net_id, None)
            self._send_gw_arp_request(floatingip)
            floatingip.update_fip_status(FIP_GW_RESOLVING_STATUS)
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = self._get_dnat_egress_match(floatingip)
        actions = [
            parser.OFPActionSetField(eth_src=fip_mac),
            parser.OFPActionSetField(eth_dst=gw_mac),
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(ipv4_src=fip_ip),
            parser.OFPActionOutput(self.external_ofport, 0)]
        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self.update_floatingip_status(
            floatingip, n_const.FLOATINGIP_STATUS_ACTIVE)

    def _remove_dnat_egress_rules(self, floatingip):
        ofproto = self.get_datapath().ofproto
        match = self._get_dnat_egress_match(floatingip)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _install_egress_nat_rules(self, floatingip):
        net = netaddr.IPNetwork(floatingip.get_external_cidr())
        if net.version != 4:
            return

        match = self._get_dnat_egress_match(floatingip)
        self.add_flow_go_to_table(self.get_datapath(),
            const.L3_LOOKUP_TABLE,
            const.PRIORITY_MEDIUM,
            const.EGRESS_NAT_TABLE,
            match=match)
        self._install_dnat_egress_rules(floatingip)

    def _remove_egress_nat_rules(self, floatingip):
        net = netaddr.IPNetwork(floatingip.get_external_cidr())
        if net.version != 4:
            return

        ofproto = self.get_datapath().ofproto
        match = self._get_dnat_egress_match(floatingip)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._remove_dnat_egress_rules(floatingip)

    def _install_ingress_nat_rules(self, floatingip):
        network_id = floatingip.get_floating_network_id()
        # TODO(Fei Rao) check the network type
        if self._is_first_external_network(network_id):
            # if it is the first floating ip on this node, then
            # install the common goto flow rule.
            parser = self.get_datapath().ofproto_parser
            match = parser.OFPMatch()
            match.set_in_port(self.external_ofport)
            self.add_flow_go_to_table(self.get_datapath(),
                const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                const.PRIORITY_DEFAULT,
                const.INGRESS_NAT_TABLE,
                match=match)
        self._install_floatingip_arp_responder(floatingip)
        self._install_mac_learning_rules(floatingip)
        self._install_dnat_ingress_rules(floatingip)
        self._increase_external_network_count(network_id)

    def _remove_ingress_nat_rules(self, floatingip):
        network_id = floatingip.get_floating_network_id()
        if self._is_last_external_network(network_id):
            # if it is the last floating ip on this node, then
            # remove the common goto flow rule.
            parser = self.get_datapath().ofproto_parser
            ofproto = self.get_datapath().ofproto
            match = parser.OFPMatch()
            match.set_in_port(self.external_ofport)
            self.mod_flow(
                self.get_datapath(),
                command=ofproto.OFPFC_DELETE,
                table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                priority=const.PRIORITY_DEFAULT,
                match=match)
        self._remove_floatingip_arp_responder(floatingip)
        self._remove_mac_learning_rules(floatingip)
        self._remove_dnat_ingress_rules(floatingip)
        self._decrease_external_network_count(network_id)

    def update_floatingip_status(self, floatingip, status):
        floatingip.update_fip_status(status)
        self.nb_api.update_floatingip(id=floatingip.get_id(),
                                      topic=floatingip.get_topic(),
                                      notify=False,
                                      status=status)

    def associate_floatingip(self, floatingip):
        self._install_ingress_nat_rules(floatingip)
        self._install_egress_nat_rules(floatingip)

    def disassociate_floatingip(self, floatingip):
        self.delete_floatingip(floatingip)
        self.update_floatingip_status(
            floatingip, n_const.FLOATINGIP_STATUS_DOWN)

    def delete_floatingip(self, floatingip):
        self._remove_ingress_nat_rules(floatingip)
        self._remove_egress_nat_rules(floatingip)

    def update_logical_switch(self, lswitch):
        fip_groups = self.db_store.check_and_update_floatingips(
            lswitch)
        if not fip_groups:
            return
        for fip_group in fip_groups:
            fip, old_fip = fip_group
            # save to df db
            self.nb_api.update_floatingip(
                id=fip.get_id(),
                topic=fip.get_topic(),
                notify=False,
                external_gateway_ip=fip.get_external_gateway_ip())
            # gw ip changed, so need to resolve the gw arp again
            fip.update_fip_status(FIP_GW_RESOLVING_STATUS)
            self.update_floatingip_gateway(fip, old_fip)

        fip, old_fip = fip_groups[0]
        self._set_external_gateway_mac(fip.get_floating_network_id(), None)
        self._send_gw_arp_request(fip)

    def update_floatingip_gateway(self, fip, old_fip):
        self._install_mac_learning_rules(fip, True)
        self._remove_mac_learning_rules(old_fip, True)
        # gw mac maybe change
        self._remove_dnat_egress_rules(fip)
