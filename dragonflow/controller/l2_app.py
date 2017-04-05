# Copyright (c) 2016 OpenStack Foundation.
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
from neutron_lib import constants as common_const
from oslo_log import log
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import in_proto
from ryu.ofproto import ether

from dragonflow import conf as cfg
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import nd_advertisers
from dragonflow.controller import df_base_app


# TODO(gsagie) currently the number set in Ryu for this
# (OFPP_IN_PORT) is not working, use this until resolved
# NOTE(yamamoto): Many of Nicira extensions, including
# NXAST_RESUBMIT_TABLE, take 16-bit (OpenFlow 1.0 style) port number,
# regardless of the OpenFlow version being used.
OF_IN_PORT = 0xfff8

LOG = log.getLogger(__name__)


class _LocalNetwork(object):
    def __init__(self):
        self.local_ports = {}
        self.remote_ports = {}

    def is_empty(self):
        return not self.local_ports and not self.remote_ports


class L2App(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(L2App, self).__init__(*args, **kwargs)
        self.local_networks = collections.defaultdict(_LocalNetwork)
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.is_install_l2_responder = cfg.CONF.df_l2_app.l2_responder

    def switch_features_handler(self, ev):
        self.add_flow_go_to_table(const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)
        self.add_flow_go_to_table(const.ARP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)
        self.add_flow_go_to_table(const.IPV6_ND_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)

        # ARP traffic => send to ARP table
        match = self.parser.OFPMatch(eth_type=0x0806)
        self.add_flow_go_to_table(const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.ARP_TABLE, match=match)

        # Neighbor Discovery traffic => send to ND table
        match = self.parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IPV6)
        match.set_ip_proto(in_proto.IPPROTO_ICMPV6)
        self.add_flow_go_to_table(const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.IPV6_ND_TABLE, match=match)

        # Default: traffic => send to connection track table
        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.EGRESS_CONNTRACK_TABLE)

        # Default: traffic => send to service classification table
        self.add_flow_go_to_table(const.EGRESS_CONNTRACK_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.SERVICES_CLASSIFICATION_TABLE)

        # Default: traffic => send to dispatch table
        self.add_flow_go_to_table(const.INGRESS_CONNTRACK_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.INGRESS_DISPATCH_TABLE)

        # Clear local networks cache so the multicast/broadcast flows
        # are installed correctly
        self.local_networks.clear()

    def _add_l2_responders(self, lport):
        if not self.is_install_l2_responder:
            return
        ips = lport.get_ip_list()
        network_id = lport.get_external_value('local_network_id')
        mac = lport.get_mac()
        for ip in ips:
            ip_version = netaddr.IPAddress(ip).version
            if ip_version == 4:
                arp_responder.ArpResponder(self,
                                           network_id, ip, mac).add()
            elif ip_version == 6:
                nd_advertisers.NeighAdvertiser(self,
                                               network_id, ip, mac).add()

    def _remove_l2_responders(self, lport):
        if not self.is_install_l2_responder:
            return
        ips = lport.get_ip_list()
        network_id = lport.get_external_value('local_network_id')
        for ip in ips:
            ip_version = netaddr.IPAddress(ip).version
            if ip_version == 4:
                arp_responder.ArpResponder(self,
                                           network_id, ip).remove()
            elif ip_version == 6:
                nd_advertisers.NeighAdvertiser(self,
                                               network_id, ip).remove()

    def remove_local_port(self, lport):
        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        network_type = lport.get_external_value('network_type')
        segmentation_id = lport.get_external_value('segmentation_id')
        port_key = lport.get_unique_key()
        topic = lport.get_topic()
        device_owner = lport.get_device_owner()

        parser = self.parser
        ofproto = self.ofproto

        # Remove destination classifier for port
        if device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._delete_dst_classifier_flow_for_port(network_id, mac)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._remove_l2_responders(lport)

        self._remove_local_port(lport_id,
                                mac,
                                topic,
                                network_id,
                                segmentation_id,
                                network_type)

    def _remove_local_port(self, lport_id, mac, topic,
                           local_network_id, segmentation_id,
                           network_type):
        parser = self.parser
        ofproto = self.ofproto

        # Remove ingress destination lookup for port
        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Update multicast and broadcast
        self._del_multicast_broadcast_handling_for_local(lport_id,
                                                         topic,
                                                         local_network_id)

    def _del_multicast_broadcast_handling_for_local(self,
                                                    lport_id,
                                                    topic,
                                                    local_network_id):
        # update local ports
        network = self.local_networks.get(local_network_id)
        if network is None:
            return

        if lport_id not in network.local_ports:
            return

        del network.local_ports[lport_id]

        if not network.local_ports:
            self._del_multicast_broadcast_flows_for_local(local_network_id)
            if network.is_empty():
                del self.local_networks[local_network_id]
        else:
            self._update_multicast_broadcast_flows_for_local(
                network.local_ports,
                topic,
                local_network_id)

    def _del_multicast_broadcast_flows_for_local(self, local_network_id):
        ofproto = self.ofproto

        # Ingress for broadcast and multicast
        match = self._get_multicast_broadcast_match(local_network_id)

        self.mod_flow(
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Egress for broadcast and multicast
        match = self._get_multicast_broadcast_match(local_network_id)

        self.mod_flow(
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _update_multicast_broadcast_flows_for_local(self, local_ports, topic,
                                                    local_network_id):
        parser = self.parser
        ofproto = self.ofproto
        command = ofproto.OFPFC_MODIFY

        # Ingress broadcast
        ingress = []
        egress = []

        for port_id_in_network in local_ports:
            lport = self.db_store.get_port(port_id_in_network, topic)
            if lport is None:
                continue
            port_key_in_network = local_ports[port_id_in_network]

            egress.append(parser.OFPActionSetField(reg7=port_key_in_network))
            egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                       const.EGRESS_TABLE))

            ingress.append(parser.OFPActionSetField(reg7=port_key_in_network))
            ingress.append(parser.NXActionResubmitTable(
                OF_IN_PORT, const.INGRESS_CONNTRACK_TABLE))

        egress.append(parser.OFPActionSetField(reg7=0))
        egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                   const.EGRESS_TABLE))
        # Egress broadcast
        match = self._get_multicast_broadcast_match(local_network_id)
        egress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, egress)]
        self.mod_flow(
            inst=egress_inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Ingress broadcast
        match = self._get_multicast_broadcast_match(local_network_id)
        ingress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, ingress)]
        self.mod_flow(
            inst=ingress_inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def remove_remote_port(self, lport):
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        device_owner = lport.get_device_owner()

        # Remove destination classifier for port
        if device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._delete_dst_classifier_flow_for_port(network_id, mac)

        self._remove_l2_responders(lport)

    def _add_dst_classifier_flow_for_port(self, network_id, mac, port_key):
        parser = self.parser
        ofproto = self.ofproto

        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = [parser.OFPActionSetField(reg7=port_key)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _delete_dst_classifier_flow_for_port(self, network_id, mac):
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def add_local_port(self, lport):
        lport_id = lport.get_id()
        mac = lport.get_mac()
        ofport = lport.get_external_value('ofport')
        port_key = lport.get_unique_key()
        network_id = lport.get_external_value('local_network_id')

        if ofport is None or network_id is None:
            return

        topic = lport.get_topic()

        parser = self.parser
        ofproto = self.ofproto

        # REVISIT(xiaohhui): This check might be removed when l3-agent is
        # obsoleted.
        if lport.get_device_owner() != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_dst_classifier_flow_for_port(network_id, mac, port_key)

        # Go to dispatch table according to unique metadata & mac
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = [parser.OFPActionSetField(reg7=port_key)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_CONNTRACK_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
        inst = [parser.OFPInstructionGotoTable(const.INGRESS_CONNTRACK_TABLE)]
        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self._add_multicast_broadcast_handling_for_local_port(lport_id,
                                                              port_key,
                                                              network_id,
                                                              topic)
        self._add_l2_responders(lport)

    def _add_multicast_broadcast_handling_for_local_port(self,
                                                         lport_id,
                                                         port_key,
                                                         network_id,
                                                         topic):
        parser = self.parser
        ofproto = self.ofproto
        command = ofproto.OFPFC_MODIFY

        local_network = self.local_networks[network_id]
        if not local_network.local_ports:
            command = ofproto.OFPFC_ADD

        local_network.local_ports[lport_id] = port_key

        ingress = []
        ingress.append(parser.OFPActionSetField(reg7=port_key))
        ingress.append(parser.NXActionResubmitTable(
            OF_IN_PORT,
            const.INGRESS_CONNTRACK_TABLE))

        egress = []

        egress.append(parser.OFPActionSetField(reg7=port_key))
        egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                   const.EGRESS_TABLE))

        for port_id_in_network in local_network.local_ports:
            lport = self.db_store.get_port(port_id_in_network, topic)
            if lport is None or lport_id == lport.get_id():
                continue
            port_key_in_network = local_network.local_ports[port_id_in_network]

            egress.append(parser.OFPActionSetField(reg7=port_key_in_network))
            egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                       const.EGRESS_TABLE))

            ingress.append(parser.OFPActionSetField(reg7=port_key_in_network))
            ingress.append(parser.NXActionResubmitTable(
                OF_IN_PORT,
                const.INGRESS_CONNTRACK_TABLE))

        egress.append(parser.OFPActionSetField(reg7=0))
        egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                   const.EGRESS_TABLE))
        # Egress broadcast
        match = self._get_multicast_broadcast_match(network_id)
        egress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, egress)]
        self.mod_flow(
            inst=egress_inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Ingress broadcast
        match = self._get_multicast_broadcast_match(network_id)
        ingress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, ingress)]
        self.mod_flow(
            inst=ingress_inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def remove_logical_switch(self, lswitch):
        ofproto = self.ofproto

        network_id = lswitch.get_unique_key()
        match = self._get_multicast_broadcast_match(network_id)

        self.mod_flow(
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def add_remote_port(self, lport):
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        port_key = lport.get_unique_key()

        # Router MAC's go to L3 table will be taken care by l3 app
        # REVISIT(xiaohhui): This check might be removed when l3-agent is
        # obsoleted.
        if lport.get_device_owner() != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_dst_classifier_flow_for_port(network_id, mac, port_key)

        self._add_l2_responders(lport)

    def _get_multicast_broadcast_match(self, network_id):
        match = self.parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)
        return match
