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

from neutron.common import constants as common_const

from ryu.lib.mac import haddr_to_bin
from dragonflow._i18n import _
from dragonflow.controller.common.arp_responder import ArpResponder
from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp
from dragonflow._i18n import _LI

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
        ip = lport.get_ip()
        if netaddr.IPAddress(ip).version != 4:
            return
        network_id = lport.get_external_value('local_network_id')
        mac = lport.get_mac()
        ArpResponder(self.get_datapath(), network_id, ip, mac).add()

    def _remove_arp_responder(self, lport):
        if not self.is_install_arp_responder:
            return
        ip = lport.get_ip()
        if netaddr.IPAddress(ip).version != 4:
            return
        network_id = lport.get_external_value('local_network_id')
        ArpResponder(self.get_datapath(), network_id, ip).remove()

    def remove_local_port(self, lport):

        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        network_type = lport.get_external_value('network_type')
        segmentation_id = lport.get_external_value('segmentation_id')
        ofport = lport.get_external_value('ofport')
        port_key = lport.get_tunnel_key()
        topic = lport.get_topic()

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

        match = parser.OFPMatch(reg7=port_key)
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

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self._remove_arp_responder(lport)

        if network_type is not None and segmentation_id is not None:
            self._remove_local_port_with_seg(lport_id,
                                             mac,
                                             topic,
                                             network_id,
                                             segmentation_id)
            return

        # Remove dispatch to local port according to unique tunnel_id
        match = parser.OFPMatch(tunnel_id_nxm=port_key)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self._del_multicast_broadcast_handling_for_port(network_id, lport_id)

    def _remove_local_port_with_seg(self, lport_id, mac, topic,
                                    network_id, segmentation_id):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Remove ingress destination lookup for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Update multicast and broadcast
        self._del_multicast_broadcast_handling_for_local_with_seg(
            lport_id, topic, network_id)
        self._del_network_flows_on_last_port_down(segmentation_id)

    def _remove_remote_port_with_seg(self, lport_id,
                                     topic, network_id):
        self._del_multicast_broadcast_handling_for_remote_with_seg(
            lport_id, topic, network_id)

    def _del_multicast_broadcast_handling_for_local_with_seg(self,
                                                             lport_id,
                                                             topic,
                                                             network_id):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        command = ofproto.OFPFC_MODIFY

        # update local ports
        network = self.local_networks.get(network_id)
        if network is None:
            return

        local_ports = network.get('local')
        if local_ports is None:
            return

        if lport_id not in local_ports:
            return

        del local_ports[lport_id]

        ingress = []

        egress = []
        egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                   const.EGRESS_TABLE))

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

        # Egress broadcast
        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)
        egress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, egress)]
        self.mod_flow(
            self.get_datapath(),
            inst=egress_inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Ingress broadcast
        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)
        ingress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, ingress)]
        self.mod_flow(
            self.get_datapath(),
            inst=ingress_inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)
        return

    def remove_remote_port(self, lport):

        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        tunnel_key = lport.get_tunnel_key()
        topic = lport.get_topic()
        network_type = lport.get_external_value('network_type')
        segmentation_id = lport.get_external_value('segmentation_id')

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Remove destination classifier for port
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

        self._remove_arp_responder(lport)

        if network_type is not None and segmentation_id is not None:
            self._remove_remote_port_with_seg(lport_id,
                                              topic,
                                              network_id)
            return

        self._del_multicast_broadcast_handling_for_port(network_id, lport_id)

    def add_local_port(self, lport):

        if self.get_datapath() is None:
            return

        lport_id = lport.get_id()
        mac = lport.get_mac()
        ofport = lport.get_external_value('ofport')
        port_key = lport.get_tunnel_key()
        network_id = lport.get_external_value('local_network_id')
        network_type = lport.get_external_value('network_type')
        segmentation_id = lport.get_external_value('segmentation_id')
        if segmentation_id is not None:
            segmentation_id = int(segmentation_id)
        topic = lport.get_topic()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        actions = []
        actions.append(parser.OFPActionSetField(reg6=port_key))
        actions.append(parser.OFPActionSetField(metadata=network_id))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.EGRESS_CONNTRACK_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Dispatch to local port according to unique tunnel_id
        match = parser.OFPMatch(reg7=port_key)
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

        # Destination classifier for port
        priority = const.PRIORITY_MEDIUM
        goto_table = const.EGRESS_TABLE

        # Router MAC's go to L3 table and have higher priority
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            priority = const.PRIORITY_HIGH
            goto_table = const.L3_LOOKUP_TABLE

        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = []
        actions.append(parser.OFPActionSetField(reg7=port_key))
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

        if network_type is not None and segmentation_id is not None:
            self._add_local_port_with_seg(lport, lport_id,
                                          port_key, mac, network_id,
                                          network_type,
                                          segmentation_id, topic)

            return

        # Go to dispatch table according to unique tunnel_id
        match = parser.OFPMatch(tunnel_id_nxm=port_key)
        actions = [parser.OFPActionSetField(reg7=port_key),
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

        # Egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
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
                                                        port_key)

        self._add_arp_responder(lport)

    def _add_local_port_with_seg(self, lport, lport_id,
                                 port_key, mac, network_id, network_type,
                                 segmentation_id, topic):
        LOG.info(_LI("Adding local port with segmentation"))

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Ingress
        # Go to dispatch table according to unique tunnel_id
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = [parser.OFPActionSetField(reg7=port_key)]
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_CONNTRACK_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
        inst = [parser.OFPInstructionGotoTable(const.INGRESS_CONNTRACK_TABLE)]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self._install_network_flows_on_first_port_up(segmentation_id,
                                                     network_id)
        self._add_multicast_broadcast_handling_for_local_port(lport_id,
                                                              port_key,
                                                              network_id,
                                                              topic)
        self._add_arp_responder(lport)

    def _install_network_flows_on_first_port_up(self,
                                                segmentation_id,
                                                local_network_id):

        LOG.info(_LI("Install network flows on frist port up "
                     "segmentation_id =%(segmentation_id), "
                     "local_network_id port = %(local_network_id)") %
                 {'segmentation_id': str(segmentation_id),
                  'local_network_id': str(local_network_id)})
        network = self.local_networks.get(local_network_id)
        if network is not None and network.values is not None:
            local_ports = network.get('local')
            if local_ports is not None and local_ports.values is not None:
                return

        self._install_network_flows_for_tunnel(segmentation_id,
                                               local_network_id)

    def _del_network_flows_on_last_port_down(self,
                                             segmentation_id,
                                             local_network_id):
        LOG.info(_LI("Delete network on last port down "
                     "segmentation_id =%(segmentation_id), "
                     "local_network_id port = %(local_network_id)") %
                 {'segmentation_id': str(segmentation_id),
                  'local_network_id': str(local_network_id)})

        network = self.local_networks.get(local_network_id)
        if network is not None and network.values is not None:
            local_ports = network.get('local')
            if local_ports is not None and local_ports.values is not None:
                return

        self._del_network_flows_for_tunnel(segmentation_id)

    # Install Ingress network flow for vxlan
    # Table=INGRESS_CLASSIFICATION_DISPATCH_TABLE, priority=Medium
    # Match: tunnel_id= vni
    # Actions: metadata=network_id, goto:INGRESS_DESTIANTION_PORT_LOOKUP_TABLE
    def _install_network_flows_for_tunnel(self,
                                          segmentation_id,
                                          local_network_id):
        LOG.info(_LI("Install network flows for tunnel "
                     "segmentation_id =%(segmentation_id), "
                     "local_network_id port = %(local_network_id)") %
                 {'segmentation_id': str(segmentation_id),
                  'local_network_id': str(local_network_id)})
        if segmentation_id is None:
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(tunnel_id_nxm=segmentation_id)

        actions = []
        actions.append(parser.OFPActionSetField(metadata=local_network_id))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _del_network_flows_for_tunnel(self, segmentation_id):
        LOG.info(_LI("Delete network for tunnel: segmentation_id =%s") %
                 str(segmentation_id))
        if segmentation_id is None:
            return

        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(tunnel_id_nxm=segmentation_id)

        self.mod_flow(
            self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _add_multicast_broadcast_handling_for_local_port(self,
                                                         lport_id,
                                                         port_key,
                                                         network_id,
                                                         topic):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        command = ofproto.OFPFC_MODIFY
        network = self.local_networks.get(network_id)
        if network is None:
            local_ports = {}
            network = {}
            network['local'] = local_ports
            self.local_networks[network_id] = network
            command = ofproto.OFPFC_ADD

        local_ports = network.get('local')
        if local_ports is None:
            local_ports = {}
            network['local'] = local_ports
            command = ofproto.OFPFC_ADD

        local_ports[lport_id] = port_key

        ingress = []
        ingress.append(parser.OFPActionSetField(reg7=port_key))
        ingress.append(parser.NXActionResubmitTable(
            OF_IN_PORT,
            const.INGRESS_CONNTRACK_TABLE))

        egress = []
        egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                   const.EGRESS_TABLE))
        egress.append(parser.OFPActionSetField(reg7=port_key))
        egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                   const.EGRESS_TABLE))

        for port_id_in_network in local_ports:
            lport = self.db_store.get_port(port_id_in_network, topic)
            if lport is None or lport_id == lport.get_id():
                continue
            port_key_in_network = local_ports[port_id_in_network]

            egress.append(parser.OFPActionSetField(reg7=port_key_in_network))
            egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                       const.EGRESS_TABLE))

            ingress.append(parser.OFPActionSetField(reg7=port_key_in_network))
            ingress.append(parser.NXActionResubmitTable(
                OF_IN_PORT,
                const.INGRESS_CONNTRACK_TABLE))

        # Egress broadcast
        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)
        egress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS,
            egress)]
        self.mod_flow(
            self.get_datapath(),
            inst=egress_inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Ingress broadcast
        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)
        ingress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, ingress)]
        self.mod_flow(
            self.get_datapath(),
            inst=ingress_inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _del_multicast_broadcast_handling_for_remote_with_seg(self,
                                                              lport_id,
                                                              network_id,
                                                              segmentation_id):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        command = self.get_datapath().ofproto.OFPFC_MODIFY
        network = self.local_networks.get(network_id)
        if network is None:
            return

        remote_ports = network.get('remote')
        if remote_ports is None:
            return

        del remote_ports[lport_id]

        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)

        actions = []
        tunnels = {}

        # aggregate  remote tunnel
        for port_id_in_network in remote_ports:
            lport = self.db_store.get_port(self, port_id_in_network)
            if lport is None:
                continue
            tunnel_port = lport.get_external_value('ofport')

            if tunnels[tunnel_port] is None:
                tunnels[tunnel_port] = tunnel_port
                actions.append(parser.OFPActionSetField(
                    tunel_id_nxm=segmentation_id))
                actions.append(parser.OFPActionOutput(port=tunnel_port))

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _add_multicast_broadcast_handling_for_remote_port(self,
                                                          lport_id,
                                                          port_key,
                                                          network_id,
                                                          segmentation_id,
                                                          ofport):
        LOG.info(_LI("Adding multicast and broadcast for remote port"))
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        command = self.get_datapath().ofproto.OFPFC_MODIFY

        network = self.local_networks.get(network_id)
        if network is None:
            remote_ports = {}
            network = {}
            network['remote'] = remote_ports
            self.local_networks[network_id] = network
            command = self.get_datapath().ofproto.OFPFC_ADD

        remote_ports = network.get('remote')
        if remote_ports is None:
            remote_ports = {}
            network['remote'] = remote_ports
            command = self.get_datapath().ofproto.OFPFC_ADD
        remote_ports[lport_id] = port_key

        match = parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)

        actions = []
        actions.append(parser.OFPActionSetField(tunnel_id_nxm=segmentation_id))
        actions.append(parser.OFPActionOutput(port=ofport))

        tunnels = {}
        tunnels[ofport] = ofport

        # todo
        # aggregate  remote tunnel
        for port_id_in_network in remote_ports:
            lport = self.db_store.get_port(self, port_id_in_network)
            if lport is None:
                continue
            tunnel_port = lport.get_external_value('ofport')

            if tunnels[tunnel_port] is None:
                tunnels[tunnel_port] = tunnel_port
                actions.append(parser.OFPActionSetField(
                    tunel_id_nxm=segmentation_id))
                actions.append(parser.OFPActionOutput(port=tunnel_port))

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=command,
            priority=const.PRIORITY_LOW,
            match=match)

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
        network_type = lport.get_external_value('network_type')
        segmentation_id = lport.get_external_value('segmentation_id')
        ofport = lport.get_external_value('ofport')
        port_key = lport.get_tunnel_key()

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # Destination classifier for port
        priority = const.PRIORITY_MEDIUM
        goto_table = const.EGRESS_TABLE

        # Router MAC's go to L3 table and have higher priority
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            priority = const.PRIORITY_HIGH
            goto_table = const.L3_LOOKUP_TABLE

        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = []
        actions.append(parser.OFPActionSetField(reg7=port_key))
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

        if network_type is not None and segmentation_id is not None:
            self._add_remote_with_seg(lport, lport_id, port_key,
                                      ofport,
                                      network_id,
                                      segmentation_id)
            return

        # Egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
        actions = []
        actions.append(parser.OFPActionSetField(tunnel_id_nxm=port_key))
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
                                                        port_key)

        self._add_arp_responder(lport)

    def _add_remote_with_seg(self, lport, lport_id, port_key,
                             ofport, network_id,
                             segmentation_id):
        LOG.info(_LI("Add remote with segmentation"))

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        match = parser.OFPMatch(reg7=port_key)
        actions = []
        actions.append(parser.OFPActionSetField(tunnel_id_nxm=segmentation_id))
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

        self._add_multicast_broadcast_handling_for_remote_port(lport_id,
                                                               port_key,
                                                               network_id,
                                                               segmentation_id,
                                                               ofport)
        self._add_arp_responder(lport)

    def _install_flows_on_switch_up(self):
        # Clear local networks cache so the multicast/broadcast flows
        # are installed correctly
        self.local_networks.clear()
        for port in self.db_store.get_ports():
            if port.get_external_value('is_local'):
                self.add_local_port(port)
            else:
                self.add_remote_port(port)
