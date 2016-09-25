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
from neutron_lib import constants as n_const
from oslo_config import cfg
from ryu.ofproto import ether
import six

from dragonflow._i18n import _
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app


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
]

FIP_GW_RESOLVING_STATUS = 'resolving'


class DNATApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(DNATApp, self).__init__(*args, **kwargs)
        cfg.CONF.register_opts(DF_DNAT_APP_OPTS, group='df_dnat_app')
        self.external_network_bridge = \
            cfg.CONF.df_dnat_app.external_network_bridge
        self.external_bridge_mac = ""
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.int_peer_patch_port = cfg.CONF.df_dnat_app.int_peer_patch_port
        self.ex_peer_patch_port = cfg.CONF.df_dnat_app.ex_peer_patch_port
        self.external_networks = collections.defaultdict(int)
        self.local_floatingips = collections.defaultdict(str)

    def switch_features_handler(self, ev):
        self._init_external_bridge()
        self._install_output_to_physical_patch(self.external_ofport)

    def ovs_port_updated(self, ovs_port):
        if ovs_port.get_name() != self.external_network_bridge:
            return

        mac = ovs_port.get_mac_in_use()
        if (self.external_bridge_mac == mac
                or not mac
                or mac == '00:00:00:00:00:00'):
            return

        for key, floatingip in six.iteritems(self.local_floatingips):
            self._install_dnat_egress_rules(floatingip, mac)

        self.external_bridge_mac = mac

    def _init_external_bridge(self):
        self.external_ofport = self.vswitch_api.create_patch_port(
            self.integration_bridge,
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

    def _install_floatingip_arp_responder(self, floatingip):
        # install floatingip arp responder flow rules
        if netaddr.IPAddress(floatingip.get_ip_address()).version != 4:
            return
        arp_responder.ArpResponder(self.get_datapath(),
             None,
             floatingip.get_ip_address(),
             floatingip.get_mac_address(),
             const.INGRESS_NAT_TABLE).add()

    def _remove_floatingip_arp_responder(self, floatingip):
        # install floatingip arp responder flow rules
        if netaddr.IPAddress(floatingip.get_ip_address()).version != 4:
            return
        arp_responder.ArpResponder(self.get_datapath(),
             None,
             floatingip.get_ip_address(),
             floatingip.get_mac_address(),
             const.INGRESS_NAT_TABLE).remove()

    def _get_vm_port_info(self, floatingip):
        lport = self.db_store.get_local_port(floatingip.get_lport_id())
        mac = lport.get_mac()
        ip = lport.get_ip()
        tunnel_key = lport.get_tunnel_key()
        local_network_id = lport.get_external_value('local_network_id')

        return mac, ip, tunnel_key, local_network_id

    def _get_vm_gateway_info(self, floatingip):
        lport = self.db_store.get_local_port(floatingip.get_lport_id())
        lrouter = self.db_store.get_router(floatingip.get_lrouter_id())
        for router_port in lrouter.get_ports():
            if router_port.get_lswitch_id() == lport.get_lswitch_id():
                return router_port.get_mac()
        return None

    def _install_dnat_ingress_rules(self, floatingip):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ipv4_dst=floatingip.get_ip_address())

        vm_mac, vm_ip, vm_tunnel_key, local_network_id = \
            self._get_vm_port_info(floatingip)
        vm_gateway_mac = self._get_vm_gateway_info(floatingip)
        if vm_gateway_mac is None:
            vm_gateway_mac = floatingip.get_mac_address()
        actions = [
            parser.OFPActionSetField(eth_src=vm_gateway_mac),
            parser.OFPActionSetField(eth_dst=vm_mac),
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(ipv4_dst=vm_ip),
            parser.OFPActionSetField(reg7=vm_tunnel_key),
            parser.OFPActionSetField(metadata=local_network_id)
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
        _, vm_ip, _, local_network_id = self._get_vm_port_info(floatingip)
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                metadata=local_network_id,
                                ipv4_src=vm_ip)
        return match

    def _install_dnat_egress_rules(self, floatingip, network_bridge_mac):
        fip_mac = floatingip.get_mac_address()
        fip_ip = floatingip.get_ip_address()
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = self._get_dnat_egress_match(floatingip)
        actions = [
            parser.OFPActionSetField(eth_src=fip_mac),
            parser.OFPActionSetField(eth_dst=network_bridge_mac),
            parser.OFPActionSetField(ipv4_src=fip_ip)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_EXTERNAL_TABLE)

        inst = [action_inst, goto_inst]

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
        if self.external_bridge_mac:
            self._install_dnat_egress_rules(floatingip,
                                            self.external_bridge_mac)

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
        self._remove_dnat_ingress_rules(floatingip)
        self._decrease_external_network_count(network_id)

    def update_floatingip_status(self, floatingip, status):
        floatingip.update_fip_status(status)
        self.nb_api.update_floatingip(id=floatingip.get_id(),
                                      topic=floatingip.get_topic(),
                                      notify=False,
                                      status=status)

    def associate_floatingip(self, floatingip):
        self.local_floatingips[floatingip.get_id()] = floatingip
        self._install_ingress_nat_rules(floatingip)
        self._install_egress_nat_rules(floatingip)

    def disassociate_floatingip(self, floatingip):
        self.local_floatingips.pop(floatingip.get_id(), 0)
        self.delete_floatingip(floatingip)
        self.update_floatingip_status(
            floatingip, n_const.FLOATINGIP_STATUS_DOWN)

    def remove_local_port(self, lport):
        port_id = lport.get_id()
        ips_to_disassociate = [
            fip for fip in six.itervalues(self.local_floatingips)
            if fip.get_lport_id() == port_id]
        for floatingip in ips_to_disassociate:
            self.delete_floatingip(floatingip)
            self.update_floatingip_status(
                floatingip, n_const.FLOATINGIP_STATUS_DOWN)

    def add_local_port(self, lport):
        port_id = lport.get_id()
        ips_to_associate = [
            fip for fip in six.itervalues(self.local_floatingips)
            if fip.get_lport_id() == port_id]
        for floatingip in ips_to_associate:
            self._install_ingress_nat_rules(floatingip)
            self._install_egress_nat_rules(floatingip)

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

    def _install_output_to_physical_patch(self, ofport):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        actions = [parser.OFPActionOutput(ofport,
                                          ofproto.OFPCML_NO_BUFFER)]
        actions_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [actions_inst]
        self.mod_flow(self.get_datapath(), inst=inst,
                      table_id=const.EGRESS_EXTERNAL_TABLE,
                      priority=const.PRIORITY_MEDIUM, match=None)
