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
from neutron_lib import constants as common_const
from oslo_config import cfg
from ryu.lib.mac import haddr_to_bin

from dragonflow._i18n import _
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app

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


class L2App(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(L2App, self).__init__(*args, **kwargs)
        self.local_networks = {}
        cfg.CONF.register_opts(DF_L2_APP_OPTS, group='df_l2_app')
        self.is_install_arp_responder = cfg.CONF.df_l2_app.l2_responder

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

        # Clear local networks cache so the multicast/broadcast flows
        # are installed correctly
        self.local_networks.clear()

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
        arp_responder.ArpResponder(self.get_datapath(),
                                   network_id, ip, mac).add()

    def _remove_arp_responder(self, lport):
        if not self.is_install_arp_responder:
            return
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            return
        ip = lport.get_ip()
        if netaddr.IPAddress(ip).version != 4:
            return
        network_id = lport.get_external_value('local_network_id')
        arp_responder.ArpResponder(self.get_datapath(),
                                   network_id, ip).remove()

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
            command=ofproto.OFPFC_DELETE,
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
