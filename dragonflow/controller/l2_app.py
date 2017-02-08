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
from neutron_lib.utils import helpers
from oslo_log import log
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import in_proto
from ryu.ofproto import ether

from dragonflow._i18n import _, _LI, _LE
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
        self.bridge_mappings = self._parse_bridge_mappings(
            cfg.CONF.df_l2_app.bridge_mappings)
        self.int_ofports = {}

    def _parse_bridge_mappings(self, bridge_mappings):
        try:
            return helpers.parse_mappings(bridge_mappings)
        except ValueError as e:
            raise ValueError(_("Parsing bridge_mappings failed: %s.") % e)

    def setup_physical_bridges(self, bridge_mappings):
        '''Setup the physical network bridges.

        Creates physical network bridges and links them to the
        integration bridge using veths or patch ports.

        :param bridge_mappings: map physical network names to bridge names.
        '''
        for physical_network, bridge in bridge_mappings.items():
            LOG.info(_LI("Mapping physical network %(physical_network)s to "
                         "bridge %(bridge)s"),
                     {'physical_network': physical_network,
                      'bridge': bridge})

            int_ofport = self.vswitch_api.create_patch_port(
                self.integration_bridge,
                'int-' + bridge,
                'phy-' + bridge)
            self.vswitch_api.create_patch_port(
                bridge,
                'phy-' + bridge,
                'int-' + bridge)
            self.int_ofports[physical_network] = int_ofport

    def switch_features_handler(self, ev):
        self.setup_physical_bridges(self.bridge_mappings)
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
        ofport = lport.get_external_value('ofport')
        port_key = lport.get_unique_key()
        topic = lport.get_topic()
        device_owner = lport.get_device_owner()

        parser = self.parser
        ofproto = self.ofproto

        # Remove ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        match = parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            table_id=const.INGRESS_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

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
        self._del_network_flows_on_last_port_down(local_network_id,
                                                  segmentation_id,
                                                  network_type)

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
            priority=const.PRIORITY_HIGH,
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
            priority=const.PRIORITY_HIGH,
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
        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        tunnel_key = lport.get_unique_key()
        segmentation_id = lport.get_external_value('segmentation_id')
        device_owner = lport.get_device_owner()

        parser = self.parser
        ofproto = self.ofproto

        # Remove destination classifier for port
        if device_owner != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._delete_dst_classifier_flow_for_port(network_id, mac)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._remove_l2_responders(lport)
        self._del_multicast_broadcast_handling_for_remote(
            lport_id, network_id, segmentation_id)

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
        network_type = lport.get_external_value('network_type')
        physical_network = lport.get_external_value('physical_network')
        segmentation_id = lport.get_external_value('segmentation_id')

        if ofport is None or network_id is None:
            return

        topic = lport.get_topic()

        parser = self.parser
        ofproto = self.ofproto

        # Ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        actions = [parser.OFPActionSetField(reg6=port_key),
                   parser.OFPActionSetField(metadata=network_id)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.EGRESS_PORT_SECURITY_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Dispatch to local port according to unique tunnel_id
        match = parser.OFPMatch(reg7=port_key)
        actions = [parser.OFPActionOutput(ofport,
                                          ofproto.OFPCML_NO_BUFFER)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Router MAC's go to L3 table will be taken care by l3 app
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
        self._install_network_flows_on_first_port_up(segmentation_id,
                                                     physical_network,
                                                     network_type,
                                                     network_id)
        self._add_multicast_broadcast_handling_for_local_port(lport_id,
                                                              port_key,
                                                              network_id,
                                                              topic)
        self._add_l2_responders(lport)

    def _del_network_flows_on_last_port_down(self,
                                             local_network_id,
                                             segmentation_id,
                                             network_type):
        network = self.local_networks.get(local_network_id)
        if network and network.local_ports:
            return

        LOG.info(_LI("Remove network flows on last port down. Network type "
                     "is %(type)s, and segmentation ID is %(s_id)s."),
                 {'type': network_type, 's_id': segmentation_id})

        if network_type == 'vlan':
            self._del_network_flows_for_vlan(segmentation_id, local_network_id)
        elif network_type == 'flat':
            self._del_network_flows_for_flat(local_network_id)
        else:
            self._del_network_flows_for_tunnel(segmentation_id, network_type)

    def _del_network_flows_for_tunnel(self, segmentation_id, network_type):
        if segmentation_id is None:
            return

        parser = self.parser
        ofproto = self.ofproto

        ofport = self.vswitch_api.get_vtp_ofport(network_type)
        if not ofport:
            return

        match = parser.OFPMatch(tunnel_id_nxm=segmentation_id,
                                in_port=ofport)

        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=match)

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

    def _del_multicast_broadcast_handling_for_remote(self,
                                                     lport_id,
                                                     network_id,
                                                     segmentation_id):
        network = self.local_networks.get(network_id)
        if network is None:
            return

        if lport_id not in network.remote_ports:
            return

        del network.remote_ports[lport_id]

        if not network.remote_ports:
            self._del_multicast_broadcast_flows_for_remote(network_id)

            # delete from local_networks
            if network.is_empty():
                del self.local_networks[network_id]
        else:
            self._update_multicast_broadcast_flows_for_remote(
                network_id,
                segmentation_id,
                network.remote_ports)

    def _del_multicast_broadcast_flows_for_remote(self, network_id):
        ofproto = self.ofproto

        match = self._get_multicast_broadcast_match(network_id)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _update_multicast_broadcast_flows_for_remote(
            self, network_id, segmentation_id, remote_ports,
            command=None):
        parser = self.parser
        ofproto = self.ofproto

        if command is None:
            command = ofproto.OFPFC_MODIFY

        match = self._get_multicast_broadcast_match(network_id)

        actions = []
        remote_ips = set()
        for port_id_in_network in remote_ports:
            lport = self.db_store.get_port(port_id_in_network)
            if not lport:
                continue
            remote_ip = lport.get_external_value('peer_vtep_address')
            if remote_ip not in remote_ips:
                remote_ips.add(remote_ip)
                ofport = lport.get_external_value('ofport')
                actions.extend(
                    [parser.OFPActionSetField(tun_ipv4_dst=remote_ip),
                     parser.OFPActionSetField(tunnel_id_nxm=segmentation_id),
                     parser.OFPActionOutput(port=ofport)])

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=command,
            priority=const.PRIORITY_LOW,
            match=match)

    def _add_multicast_broadcast_handling_for_remote_port(self,
                                                          lport_id,
                                                          port_key,
                                                          network_id,
                                                          segmentation_id):
        LOG.debug("Add/update multicast and broadcast for remote port %s.",
                  lport_id)
        ofproto = self.ofproto
        command = ofproto.OFPFC_MODIFY

        local_network = self.local_networks[network_id]
        if not local_network.remote_ports:
            command = ofproto.OFPFC_ADD
        local_network.remote_ports[lport_id] = port_key
        self._update_multicast_broadcast_flows_for_remote(
            network_id, segmentation_id, local_network.remote_ports, command)

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
        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        network_type = lport.get_external_value('network_type')
        segmentation_id = lport.get_external_value('segmentation_id')
        ofport = lport.get_external_value('ofport')
        remote_ip = lport.get_external_value('peer_vtep_address')
        port_key = lport.get_unique_key()

        parser = self.parser
        ofproto = self.ofproto

        # Router MAC's go to L3 table will be taken care by l3 app
        # REVISIT(xiaohhui): This check might be removed when l3-agent is
        # obsoleted.
        if lport.get_device_owner() != common_const.DEVICE_OWNER_ROUTER_INTF:
            self._add_dst_classifier_flow_for_port(network_id, mac, port_key)

        self._add_l2_responders(lport)

        if network_type == 'vlan' or network_type == 'flat':
            return

        match = parser.OFPMatch(reg7=port_key)
        actions = [parser.OFPActionSetField(tun_ipv4_dst=remote_ip),
                   parser.OFPActionSetField(tunnel_id_nxm=segmentation_id),
                   parser.OFPActionOutput(port=ofport)]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self._add_multicast_broadcast_handling_for_remote_port(lport_id,
                                                               port_key,
                                                               network_id,
                                                               segmentation_id)

    def _install_network_flows_on_first_port_up(self,
                                                segmentation_id,
                                                physical_network,
                                                network_type,
                                                local_network_id):
        network = self.local_networks.get(local_network_id)
        if network and network.local_ports:
            return

        LOG.info(_LI("Install network flows on first port up. Network type "
                     "is %(type)s, and segmentation ID is %(s_id)s."),
                 {'type': network_type, 's_id': segmentation_id})

        if network_type == 'vlan':
            self._install_network_flows_for_vlan(segmentation_id,
                                                 physical_network,
                                                 local_network_id)
        elif network_type == 'flat':
            self._install_network_flows_for_flat(physical_network,
                                                 local_network_id)
        else:
            self._install_network_flows_for_tunnel(segmentation_id,
                                                   network_type,
                                                   local_network_id)

    """
    Install Ingress network flow for vxlan
    Table=INGRESS_CLASSIFICATION_DISPATCH_TABLE, priority=Medium
    Match: tunnel_id= vni
    Actions: metadata=network_id, goto:INGRESS_DESTIANTION_PORT_LOOKUP_TABLE
    """
    def _install_network_flows_for_tunnel(self, segmentation_id, network_type,
                                          local_network_id):
        if segmentation_id is None:
            return

        parser = self.parser
        ofproto = self.ofproto
        ofport = self.vswitch_api.get_vtp_ofport(network_type)
        if not ofport:
            return

        match = parser.OFPMatch(tunnel_id_nxm=segmentation_id,
                                in_port=ofport)

        actions = [parser.OFPActionSetField(metadata=local_network_id)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    """
    Install network flows for vlan
    """
    def _install_network_flows_for_vlan(self, segmentation_id,
                                        physical_network, local_network_id):
        # L2_LOOKUP for Remote ports
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch()

        addint = haddr_to_bin('00:00:00:00:00:00')
        add_mask_int = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, add_mask_int)
        match.set_metadata(local_network_id)
        inst = [parser.OFPInstructionGotoTable(const.EGRESS_TABLE)]
        self.mod_flow(
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # EGRESS for Remote ports
        # Table=Egress
        # Match: metadata=network_id
        # Actions: mod_vlan, output:patch
        match = parser.OFPMatch(metadata=local_network_id)
        actions = [parser.OFPActionPushVlan(ether.ETH_TYPE_8021Q),
                   parser.OFPActionSetField(
                       vlan_vid=(segmentation_id & 0x1fff) | 0x1000)]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_EXTERNAL_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        # Add EGRESS port according to physical_network
        self._install_output_to_physical_patch(physical_network,
                                               local_network_id)

        # Ingress
        # Match: dl_vlan=vlan_id,
        # Actions: metadata=network_id,
        # goto 'Destination Port Classification'
        match = parser.OFPMatch()
        match.set_vlan_vid(segmentation_id)
        actions = [parser.OFPActionSetField(metadata=local_network_id),
                   parser.OFPActionPopVlan()]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_network_flows_for_flat(self, physical_network,
                                        local_network_id):
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch()

        addint = haddr_to_bin('00:00:00:00:00:00')
        add_mask_int = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, add_mask_int)
        match.set_metadata(local_network_id)
        inst = [parser.OFPInstructionGotoTable(const.EGRESS_TABLE)]
        self.mod_flow(
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # EGRESS for Remote ports
        # Table=Egress
        match = parser.OFPMatch(metadata=local_network_id)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_EXTERNAL_TABLE)

        inst = [goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        # Add EGRESS port according to physical_network
        self._install_output_to_physical_patch(physical_network,
                                               local_network_id)

        # Ingress
        match = parser.OFPMatch(vlan_vid=0)
        actions = [parser.OFPActionSetField(metadata=local_network_id)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _del_network_flows_for_vlan(self, segmentation_id, local_network_id):
        if segmentation_id is None:
            return

        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch()
        match.set_vlan_vid(segmentation_id)
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=match)

        match = parser.OFPMatch(metadata=local_network_id)
        self.mod_flow(
            table_id=const.EGRESS_EXTERNAL_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _get_multicast_broadcast_match(self, network_id):
        match = self.parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)
        return match

    def _del_network_flows_for_flat(self, local_network_id):
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(vlan_vid=0)
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=match)

        match = parser.OFPMatch(metadata=local_network_id)
        self.mod_flow(
            table_id=const.EGRESS_EXTERNAL_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _install_output_to_physical_patch(self, physical_network,
                                          local_network_id):
        if physical_network not in self.int_ofports:
            LOG.error(_LE("Physical network %s unknown for dragonflow"),
                      physical_network)
            return

        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(metadata=local_network_id)
        ofport = self.int_ofports[physical_network]
        actions = [parser.OFPActionOutput(ofport,
                                          ofproto.OFPCML_NO_BUFFER)]
        actions_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [actions_inst]
        self.mod_flow(inst=inst,
                      table_id=const.EGRESS_EXTERNAL_TABLE,
                      priority=const.PRIORITY_HIGH, match=match)
