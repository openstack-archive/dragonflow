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

import netaddr

from ryu.lib.mac import haddr_to_bin

from dragonflow._i18n import _, _LI
from dragonflow.controller.common.arp_responder import ArpResponder
from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp

from neutron_lib import constants as common_const
from oslo_config import cfg
from oslo_log import log

DF_L2_APP_OPTS = [
    cfg.BoolOpt(
        'l2_responder',
        default=True,
        help=_('Install OVS flows to respond to ARP requests.'))
]

# TODO(gsagie) currently the number set in Ryu for this
# (OFPP_IN_PORT) is not working, use this until resolved
# NOTE(yamamoto): Many of Nicira extensions, including
# NXAST_RESUBMIT_TABLE, take 16-bit (OpenFlow 1.0 style) port number,
# regardless of the OpenFlow version being used.
OF_IN_PORT = 0xfff8

LOG = log.getLogger(__name__)


class L2App(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(L2App, self).__init__(*args, **kwargs)
        self.local_networks = {}
        self.allowed_address_pairs_mac_refs_list = {}
        cfg.CONF.register_opts(DF_L2_APP_OPTS, group='df_l2_app')
        self.is_install_arp_responder = cfg.CONF.df_l2_app.l2_responder
        self.use_active_detection_for_allowed_address_pairs = \
            cfg.CONF.df.use_active_detection_for_allowed_address_pairs

    def switch_features_handler(self, ev):
        self.add_flow_go_to_table(self.get_datapath(),
                const.SERVICES_CLASSIFICATION_TABLE,
                const.PRIORITY_DEFAULT,
                const.L2_LOOKUP_TABLE)
        self.add_flow_go_to_table(self.get_datapath(),
                const.ARP_TABLE,
                const.PRIORITY_DEFAULT,
                const.L2_LOOKUP_TABLE)

        # ARP traffic => send to ARP table
        match = self.get_datapath().ofproto_parser.OFPMatch(eth_type=0x0806)
        self.add_flow_go_to_table(self.get_datapath(),
                const.SERVICES_CLASSIFICATION_TABLE,
                const.PRIORITY_MEDIUM,
                const.ARP_TABLE, match=match)

        # Default: traffic => send to connection track table
        self.add_flow_go_to_table(self.get_datapath(),
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.EGRESS_CONNTRACK_TABLE)

        # Default: traffic => send to service classification table
        self.add_flow_go_to_table(self.get_datapath(),
                                  const.EGRESS_CONNTRACK_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.SERVICES_CLASSIFICATION_TABLE)

        # Default: traffic => send to dispatch table
        self.add_flow_go_to_table(self.get_datapath(),
                                  const.INGRESS_CONNTRACK_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.INGRESS_DISPATCH_TABLE)

        self._install_flows_on_switch_up()

    def _add_arp_responder(self, lport):
        if not self.is_install_arp_responder:
            return
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            return
        ip = lport.get_ip()
        if netaddr.IPAddress(ip).version != 4:
            return
        network_id = lport.get_external_value('local_network_id')
        mac = lport.get_mac()
        ArpResponder(self.get_datapath(), network_id, ip, mac).add()

    def _remove_arp_responder(self, lport):
        if not self.is_install_arp_responder:
            return
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            return
        ip = lport.get_ip()
        if netaddr.IPAddress(ip).version != 4:
            return
        network_id = lport.get_external_value('local_network_id')
        ArpResponder(self.get_datapath(), network_id, ip).remove()

    def _add_dst_classifier_flow_for_port(self, network_id, mac, tunnel_key):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = []
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.get_datapath().ofproto_parser\
            .OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _delete_dst_classifier_flow_for_port(self, network_id, mac):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def remove_local_port(self, lport):

        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        ofport = lport.get_external_value('ofport')
        tunnel_key = lport.get_tunnel_key()
        device_owner = lport.get_device_owner()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Remove ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Remove dispatch to local port according to unique tunnel_id
        match = parser.OFPMatch(tunnel_id_nxm=tunnel_key)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        match = parser.OFPMatch(reg7=tunnel_key)
        msg = parser.OFPFlowMod(datapath=self.get_datapath(),
                                cookie=0,
                                cookie_mask=0,
                                table_id=const.INGRESS_DISPATCH_TABLE,
                                command=ofproto.OFPFC_DELETE,
                                priority=const.PRIORITY_MEDIUM,
                                out_port=ofproto.OFPP_ANY,
                                out_group=ofproto.OFPG_ANY,
                                match=match)
        self.get_datapath().send_msg(msg)

        # Remove destination classifier for port
        if device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._delete_dst_classifier_flow_for_port(network_id, mac)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self._del_multicast_broadcast_handling_for_port(network_id, lport_id)

        self._remove_arp_responder(lport)

        self._uninstall_flows_for_allowed_address_pairs(lport)

    def remove_remote_port(self, lport):

        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        tunnel_key = lport.get_tunnel_key()
        device_owner = lport.get_device_owner()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Remove destination classifier for port
        if device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._delete_dst_classifier_flow_for_port(network_id, mac)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self._del_multicast_broadcast_handling_for_port(network_id, lport_id)

        self._remove_arp_responder(lport)

        self._uninstall_flows_for_allowed_address_pairs(lport)

    def add_local_port(self, lport):

        if self.get_datapath() is None:
            return

        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        ofport = lport.get_external_value('ofport')
        tunnel_key = lport.get_tunnel_key()
        device_owner = lport.get_device_owner()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        actions = []
        actions.append(parser.OFPActionSetField(reg6=tunnel_key))
        actions.append(parser.OFPActionSetField(metadata=network_id))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.EGRESS_PORT_SECURITY_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Go to dispatch table according to unique tunnel_id
        match = parser.OFPMatch(tunnel_id_nxm=tunnel_key)
        actions = [parser.OFPActionSetField(reg7=tunnel_key),
                   parser.OFPActionSetField(metadata=network_id)]
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_CONNTRACK_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Dispatch to local port according to unique tunnel_id
        match = parser.OFPMatch(reg7=tunnel_key)
        actions = [parser.OFPActionOutput(ofport,
                                          ofproto.OFPCML_NO_BUFFER)]
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Router MAC's go to L3 table will be handled by l3_app
        if device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_dst_classifier_flow_for_port(
                    network_id, mac, tunnel_key)

        # Egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        actions = [parser.OFPActionSetField(metadata=network_id)]
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = \
            parser.OFPInstructionGotoTable(const.INGRESS_CONNTRACK_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._add_multicast_broadcast_handling_for_port(network_id, lport_id,
                                                        tunnel_key)

        self._add_arp_responder(lport)

        self._install_flows_for_allowed_address_pairs(lport)

    def remove_logical_switch(self, lswitch):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        network_id = self.db_store.get_network_id(
            lswitch.get_id(),
        )
        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)

        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _del_multicast_broadcast_handling_for_port(self, network_id,
                                                   lport_id):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        command = self.get_datapath().ofproto.OFPFC_MODIFY
        network = self.local_networks.get(network_id)
        if network is None:
            # TODO(gsagie) add error here
            return

        if lport_id not in network:
            return

        del network[lport_id]
        self.local_networks[network_id] = network

        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)

        actions = []
        for tunnel_id in network.values():
            actions.append(parser.OFPActionSetField(reg7=tunnel_id))
            actions.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                        const.EGRESS_TABLE))

        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _add_multicast_broadcast_handling_for_port(self, network_id,
                                                   lport_id, tunnel_key):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        command = self.get_datapath().ofproto.OFPFC_MODIFY
        network = self.local_networks.get(network_id)
        if network is None:
            network = {}
            self.local_networks[network_id] = network
            command = self.get_datapath().ofproto.OFPFC_ADD

        network[lport_id] = tunnel_key

        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)

        actions = []
        for tunnel_id in network.values():
            actions.append(parser.OFPActionSetField(reg7=tunnel_id))
            actions.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                        const.EGRESS_TABLE))

        inst = [self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def add_remote_port(self, lport):

        if self.get_datapath() is None:
            return

        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        ofport = lport.get_external_value('ofport')
        tunnel_key = lport.get_tunnel_key()
        device_owner = lport.get_device_owner()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Router MAC's go to L3 table will be handled by l3_app
        if device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_dst_classifier_flow_for_port(
                    network_id, mac, tunnel_key)

        # Egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        actions = []
        actions.append(parser.OFPActionSetField(tunnel_id_nxm=tunnel_key))
        actions.append(parser.OFPActionOutput(port=ofport))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._add_multicast_broadcast_handling_for_port(network_id, lport_id,
                                                        tunnel_key)

        self._add_arp_responder(lport)

        self._install_flows_for_allowed_address_pairs(lport)

    def _install_flows_for_allowed_address_pairs(self, lport):
        # TODO(yuan wei)
        if not self.use_active_detection_for_allowed_address_pairs:
            LOG.info(_LI("Only support to use active detection"
                         "for allowed address pairs for now."))

    def _uninstall_flows_for_allowed_address_pairs(self, lport):
        # TODO(yuan wei)
        if not self.use_active_detection_for_allowed_address_pairs:
            LOG.info(_LI("Only support to use active detection"
                         "for allowed address pairs for now."))

    def _install_flows_on_switch_up(self):
        # Clear local networks cache so the multicast/broadcast flows
        # are installed correctly
        self.local_networks.clear()
        for port in self.db_store.get_ports():
            if port.get_external_value('is_local'):
                self.add_local_port(port)
            else:
                self.add_remote_port(port)

    def _install_flows_for_active_node(self, active_node):
        lport_id = active_node.get_detected_lport_id()
        lport = self.db_store.get_port(lport_id)
        if lport is None:
            return
        mac = active_node.get_detected_mac()
        ip = active_node.get_ip()
        tunnel_key = lport.get_tunnel_key()
        network_id = self.db_store.get_network_id(
            active_node.get_network_id()
        )

        if self.is_install_arp_responder:
            ArpResponder(self.get_datapath(), network_id, ip, mac,
                         const.ARP_TABLE, const.PRIORITY_LOW).add()

        if mac == lport.get_mac():
            return

        key = (network_id, mac)
        mac_refs = self.allowed_address_pairs_mac_refs_list.get(key)
        is_new_mac = False
        if mac_refs is None:
            self.allowed_address_pairs_mac_refs_list[key] = [ip]
            is_new_mac = True
        elif ip not in mac_refs:
            mac_refs.append(ip)

        if not is_new_mac:
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Destination classifier for this active node
        priority = const.PRIORITY_LOW
        goto_table = const.EGRESS_TABLE

        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = [parser.OFPActionSetField(reg7=tunnel_key)]
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(goto_table)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=priority,
            match=match)

    def _uninstall_flows_for_active_node(self, active_node):
        mac = active_node.get_detected_mac()
        ip = active_node.get_ip()
        network_id = self.db_store.get_network_id(
            active_node.get_network_id()
        )

        if self.is_install_arp_responder:
            ArpResponder(self.get_datapath(), network_id, ip,
                         const.ARP_TABLE, const.PRIORITY_LOW).remove()

        lport_id = active_node.get_detected_lport_id()
        lport = self.db_store.get_port(lport_id)
        if (lport is not None) and (mac == lport.get_mac()):
            return

        key = (network_id, mac)
        mac_refs = self.allowed_address_pairs_mac_refs_list.get(key)
        is_last_ref = False
        if (mac_refs is not None) and (ip in mac_refs):
            mac_refs.remove(ip)
            if len(mac_refs) == 0:
                del self.allowed_address_pairs_mac_refs_list[key]
                is_last_ref = True

        if not is_last_ref:
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        priority = const.PRIORITY_LOW

        # Remove destination classifier for this active node
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=priority,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def update_active_node(self, active_node, old_active_node):
        if self.get_datapath() is None:
            return

        if old_active_node:
            self._uninstall_flows_for_active_node(old_active_node)

        self._install_flows_for_active_node(active_node)

    def remove_active_node(self, active_node):
        if self.get_datapath() is None:
            return

        self._uninstall_flows_for_active_node(active_node)
