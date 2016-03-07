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
from ryu.lib.packet import arp
from ryu.lib.packet import ethernet
from ryu.lib.packet import packet
from ryu.ofproto import ether

from oslo_config import cfg
from oslo_log import log

LOG = log.getLogger(__name__)


DF_DNAT_APP_OPTS = [
    cfg.StrOpt('external_network_bridge',
              default='br-ex',
              help=_('The remote db server ip address')),
    cfg.StrOpt('int_peer_patch_port', default='patch-ex',
               help=_("Peer patch port in integration bridge for external "
                      "bridge.")),
    cfg.StrOpt('ex_peer_patch_port', default='patch-int',
               help=_("Peer patch port in external bridge for integration "
                      "bridge."))
]


class DNATApp(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(DNATApp, self).__init__(*args, **kwargs)
        self.vswitch_api = kwargs['vswitch_api']
        cfg.CONF.register_opts(DF_DNAT_APP_OPTS, group='df_dnat_app')
        self.external_network_bridge = \
            cfg.CONF.df_dnat_app.external_network_bridge
        self.int_peer_patch_port = cfg.CONF.df_dnat_app.int_peer_patch_port
        self.ex_peer_patch_port = cfg.CONF.df_dnat_app.ex_peer_patch_port
        self._create_external_bridge()
        self.external_networks = collections.defaultdict(int)
        self.external_gateway_mac = {}
        self.api.register_table_handler(const.INGRESS_NAT_TABLE,
                self.packet_in_handler)

    def _get_floatingip_by_ip(self, ip):
        floatingips = self.db_store.get_floatingips()
        for fip in floatingips:
            if fip.ip_address == ip:
                return fip
        return None

    def _get_floatingip_by_gateway(self, ip):
        floatingips = self.db_store.get_floatingips()
        for fip in floatingips:
            if fip.external_gateway_ip == ip:
                return fip
        return None

    def _update_external_gateway_mac(self, fip, learn_mac):
        net_id = fip.floating_network_id
        gw_mac = self.external_gateway_mac.get(net_id, None)
        if not gw_mac or gw_mac != learn_mac:
            self.external_gateway_mac[net_id] = learn_mac
            self._install_snat_rules(fip)

    def packet_in_handler(self, event):
        msg = event.msg
        pkt = packet.Packet(msg.data)
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is None:
            LOG.error(_LE("No support for non ARP protocol"))
            return

        if arp_pkt.opcode == arp.ARP_REPLY:
            fip1 = self._get_floatingip_by_ip(arp_pkt.dst_ip)
            fip2 = self._get_floatingip_by_gateway(arp_pkt.src_ip)
            # learn gw mac from fip arp reply packet
            if fip1 and fip2 and fip1 == fip2:
                self._update_external_gateway_mac(fip1, arp_pkt.src_mac)
        elif (arp_pkt.opcode == arp.ARP_REQUEST and
              arp_pkt.src_ip == arp_pkt.dst_ip):
            fip = self._get_floatingip_by_gateway(arp_pkt.dst_ip)
            # update gw mac from fip gateway gratuitous arp
            if fip:
                self._update_external_gateway_mac(fip, arp_pkt.src_mac)

    def _send_arp_request(self, fip):
        segmentation_id = self.db_store.get_network_id(
            fip.floating_network_id)
        segmentation_id = segmentation_id
        # check the network type, snd the packet to external gateway port
        arp_request_pkt = packet.Packet()
        arp_request_pkt.add_protocol(ethernet.ethernet(
                                     ethertype=ether.ETH_TYPE_ARP,
                                     src=fip.mac_address))

        arp_request_pkt.add_protocol(arp.arp(
                                    src_mac=fip.mac_address,
                                    src_ip=fip.ip_address,
                                    dst_ip=fip.external_gateway_ip))
        arp_request_pkt.serialize()

        self._send_packet(self.get_datapath(),
                          self.external_ofport,
                          arp_request_pkt)

    def _create_external_bridge(self):
        self.external_ofport = self.vswitch_api.create_patch_port(
            const.DRAGONFLOW_DEFAULT_BRIDGE,
            self.ex_peer_patch_port,
            self.int_peer_patch_port)
        self.vswitch_api.create_patch_port(
            self.external_network_bridge,
            self.int_peer_patch_port,
            self.ex_peer_patch_port)

    def _increase_external_network_count(self, network_id):
        self.external_networks[network_id] += 1

    def _decrease_external_network_count(self, network_id):
        self.external_networks[network_id] -= 1

    def _get_external_network_count(self, network_id):
        return self.external_networks[network_id]

    def _is_first_external_network(self, network_id):
        for key, val in six.iteritems(self.external_networks):
            if key == network_id and val != 0:
                return False
            elif key != network_id and val > 0:
                return False
        return True

    def _is_last_external_network(self, network_id):
        for key, val in six.iteritems(self.external_networks):
            if key == network_id and val != 1:
                return False
            elif key != network_id and val > 0:
                return False
        return True

    def _get_match_arp_reply(self, destination_ip, network_id=None):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_tpa(utils.ipv4_text_to_int(str(destination_ip)))
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

    def _get_instructions_packet_in(self, floatingip_id):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        actions = []
        # actions.append(parser.OFPActionSetField(metadata=floatingip_id))
        actions.append(parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER))
        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return inst

    def _install_mac_learning_rules(self, floatingip):
        # process arp reply
        match = self._get_match_arp_reply(
            floatingip.ip_address)
        instructions = self._get_instructions_packet_in(floatingip.name)
        self.mod_flow(
            self.get_datapath(),
            inst=instructions,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # process gratuitous arp
        match = self._get_match_gratuitous_arp(
            floatingip.external_gateway_ip)
        self.mod_flow(
            self.get_datapath(),
            inst=instructions,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_mac_learning_rules(self, floatingip):
        ofproto = self.get_datapath().ofproto
        # remove arp reply rules
        match = self._get_match_arp_reply(
            floatingip.ip_address)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # remove gratuitous arp rules
        match = self._get_match_gratuitous_arp(
            floatingip.external_gateway_ip)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _install_floatingip_arp_responder(self, floatingip):
        # install floatingip arp responder flow rules
        if netaddr.IPAddress(floatingip.ip_address).version != 4:
            return
        ArpResponder(self.get_datapath(),
             None,
             floatingip.ip_address,
             floatingip.mac_address,
             const.INGRESS_NAT_TABLE).add()

    def _remove_floatingip_arp_responder(self, floatingip):
        # install floatingip arp responder flow rules
        if netaddr.IPAddress(floatingip.ip_address).version != 4:
            return
        ArpResponder(self.get_datapath(),
             None,
             floatingip.ip_address,
             floatingip.mac_address,
             const.INGRESS_NAT_TABLE).remove()

    def _get_vm_port_info(self, floatingip):
        lport = self.db_store.get_local_port(
            floatingip.lport_id)
        mac = lport.get_mac()
        ip = lport.get_ip()
        ofport = lport.get_external_value('ofport')
        net_id = lport.get_lswitch_id()
        segmentation_id = self.db_store.get_network_id(
            net_id)

        return (mac, ip, ofport, segmentation_id)

    def _install_dnat_rules(self, floatingip):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ipv4_dst=floatingip.ip_address)

        vm_mac, vm_ip, vm_ofport, _ = self._get_vm_port_info(floatingip)
        fip_mac = floatingip.mac_address
        actions = []
        actions.append(parser.OFPActionSetField(eth_src=fip_mac))
        actions.append(parser.OFPActionSetField(eth_dst=vm_mac))
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(ipv4_dst=vm_ip))
        actions.append(parser.OFPActionOutput(vm_ofport, 0))
        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_dnat_rules(self, floatingip):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ipv4_dst=floatingip.ip_address)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _get_snat_match(self, floatingip):
        _, vm_ip, _, segmentation_id = self._get_vm_port_info(floatingip)
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                metadata=segmentation_id,
                                ipv4_src=vm_ip)
        return match

    def _install_snat_rules(self, floatingip):
        fip_mac = floatingip.mac_address
        fip_ip = floatingip.ip_address
        net_id = floatingip.floating_network_id
        gw_mac = self.external_gateway_mac.get(net_id, None)
        if not gw_mac:
            self._send_arp_request(floatingip)
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = self._get_snat_match(floatingip)
        actions = []
        actions.append(parser.OFPActionSetField(eth_src=fip_mac))
        actions.append(parser.OFPActionSetField(eth_dst=gw_mac))
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(ipv4_src=fip_ip))
        actions.append(parser.OFPActionOutput(self.external_ofport, 0))
        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_snat_rules(self, floatingip):
        ofproto = self.get_datapath().ofproto
        match = self._get_snat_match(floatingip)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _install_egress_nat_rules(self, floatingip):
        net = netaddr.IPNetwork(floatingip.external_cidr)
        if net.version != 4:
            return

        match = self._get_snat_match(floatingip)
        self.add_flow_go_to_table(self.get_datapath(),
            const.L3_LOOKUP_TABLE,
            const.PRIORITY_MEDIUM,
            const.EGRESS_NAT_TABLE,
            match=match)
        self._install_snat_rules(floatingip)

    def _remove_egress_nat_rules(self, floatingip):
        net = netaddr.IPNetwork(floatingip.external_cidr)
        if net.version != 4:
            return

        ofproto = self.get_datapath().ofproto
        match = self._get_snat_match(floatingip)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._remove_snat_rules(floatingip)

    def _install_ingress_nat_rules(self, floatingip):
        network_id = floatingip.floating_network_id
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
        if self._get_external_network_count(network_id) <= 0:
            # if it is the first floatingip for this external gateway,
            # install a gateway mac learning rules.
            self._install_mac_learning_rules(floatingip)
        self._install_dnat_rules(floatingip)
        self._increase_external_network_count(network_id)

    def _remove_ingress_nat_rules(self, floatingip):
        network_id = floatingip.floating_network_id
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
        if self._get_external_network_count(network_id) <= 1:
            # if it is the last flaotingip for this external gateway,
            # remove a gateway mac learning rules.
            self._remove_mac_learning_rules(floatingip)
        self._remove_dnat_rules(floatingip)
        self._decrease_external_network_count(network_id)

    def associate_floatingip(self, floatingip):
        self._install_ingress_nat_rules(floatingip)
        self._install_egress_nat_rules(floatingip)

    def disassociate_floatingip(self, floatingip):
        self._remove_ingress_nat_rules(floatingip)
        self._remove_egress_nat_rules(floatingip)
