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

import netaddr
from neutron_lib import constants as common_const
from oslo_config import cfg
from oslo_log import log
from ryu.lib.mac import haddr_to_bin
from ryu.ofproto import ether

from dragonflow._i18n import _, _LI
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

LOG = log.getLogger(__name__)


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
        ip = lport.get_ip()
        if netaddr.IPAddress(ip).version != 4:
            return
        network_id = lport.get_external_value('local_network_id')
        arp_responder.ArpResponder(self.get_datapath(),
                                   network_id, ip).remove()

    def remove_local_port(self, lport):

        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        network_type = lport.get_external_value('network_type')
        segmentation_id = lport.get_external_value('segmentation_id')
        ofport = lport.get_external_value('ofport')
        port_key = lport.get_tunnel_key()
        topic = lport.get_topic()

        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Remove ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        match = parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Remove destination classifier for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=datapath,
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            datapath=datapath,
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self._remove_arp_responder(lport)

        self._remove_local_port(lport_id,
                                mac,
                                topic,
                                network_id,
                                segmentation_id,
                                network_type)

    def _remove_local_port(self, lport_id, mac, topic,
                           local_network_id, segmentation_id,
                           network_type):
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Remove ingress destination lookup for port
        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
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

        local_ports = network.get('local')
        if local_ports is None:
            return

        if lport_id not in local_ports:
            return

        del local_ports[lport_id]

        if len(local_ports) == 0:

            self._del_multicast_broadcast_flows_for_local(local_network_id)

            # delete local_networks
            remote_ports = network.get('remote')
            if not remote_ports:
                del self.local_networks[local_network_id]

        else:
            self._update_multicast_broadcast_flows_for_local(local_ports,
                                                             topic,
                                                             local_network_id)

    def _del_multicast_broadcast_flows_for_local(self, local_network_id):
        datapath = self.get_datapath()
        ofproto = datapath.ofproto

        # Ingress for broadcast and multicast
        match = self._get_multicast_broadcast_match(local_network_id)

        self.mod_flow(
            datapath=datapath,
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Egress for broadcast and multicast
        match = self._get_multicast_broadcast_match(local_network_id)

        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _update_multicast_broadcast_flows_for_local(self, local_ports, topic,
                                                    local_network_id):
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
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
            datapath=datapath,
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
            datapath=datapath,
            inst=ingress_inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def remove_remote_port(self, lport):
        lport_id = lport.get_id()
        mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        tunnel_key = lport.get_tunnel_key()
        segmentation_id = lport.get_external_value('segmentation_id')

        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Remove destination classifier for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        self.mod_flow(
            datapath=datapath,
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        self.mod_flow(
            datapath=datapath,
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        self._remove_arp_responder(lport)
        self._del_multicast_broadcast_handling_for_remote(
            lport_id, network_id, segmentation_id)

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

        if ofport is None or network_id is None:
            return

        topic = lport.get_topic()

        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

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
            datapath=datapath,
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
            datapath=datapath,
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
        actions = [parser.OFPActionSetField(reg7=port_key)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(goto_table)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath=datapath,
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=priority,
            match=match)

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
            datapath=datapath,
            inst=inst,
            table_id=const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Egress classifier for port
        match = parser.OFPMatch(reg7=port_key)
        inst = [parser.OFPInstructionGotoTable(const.INGRESS_CONNTRACK_TABLE)]
        self.mod_flow(
            datapath=datapath,
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self._install_network_flows_on_first_port_up(segmentation_id,
                                                     network_type,
                                                     network_id)
        self._add_multicast_broadcast_handling_for_local_port(lport_id,
                                                              port_key,
                                                              network_id,
                                                              topic)
        self._add_arp_responder(lport)

    def _del_network_flows_on_last_port_down(self,
                                             local_network_id,
                                             segmentation_id,
                                             network_type):
        LOG.info(_LI("Delete network on last port down "
                     "segmentation_id =%(segmentation_id)s, "
                     "local_network_id =%(local_network_id)s") %
                 {'segmentation_id': str(segmentation_id),
                  'local_network_id': str(local_network_id)})

        network = self.local_networks.get(local_network_id, None)

        if network and network.get('local'):
            return

        if network_type == 'vlan':
            self._del_network_flows_for_vlan(segmentation_id)
        else:
            self._del_network_flows_for_tunnel(segmentation_id)

    def _del_network_flows_for_tunnel(self, segmentation_id):
        LOG.info(_LI("Delete network flows for tunnel."))
        if segmentation_id is None:
            return

        datapath = self.get_datapath()

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch(tunnel_id_nxm=segmentation_id)

        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _add_multicast_broadcast_handling_for_local_port(self,
                                                         lport_id,
                                                         port_key,
                                                         network_id,
                                                         topic):
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        command = ofproto.OFPFC_MODIFY
        network = self.local_networks.get(network_id)
        if network is None:
            network = {
                'local': {}
            }
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

        egress.append(parser.OFPActionSetField(reg7=0))
        egress.append(parser.NXActionResubmitTable(OF_IN_PORT,
                                                   const.EGRESS_TABLE))
        # Egress broadcast
        match = self._get_multicast_broadcast_match(network_id)
        egress_inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, egress)]
        self.mod_flow(
            datapath=datapath,
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
            datapath=datapath,
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

        remote_ports = network.get('remote')
        if remote_ports is None:
            return

        del remote_ports[lport_id]

        if len(remote_ports) == 0:

            self._del_multicast_broadcast_flows_for_remote(network_id)

            # delete local_networks
            local_ports = network.get('local')
            if not local_ports:
                del self.local_networks[network_id]
        else:
            self._update_multicast_broadcast_flows_for_remote(network_id,
                                                              segmentation_id,
                                                              remote_ports)

    def _del_multicast_broadcast_flows_for_remote(self, network_id):
        datapath = self.get_datapath()
        ofproto = datapath.ofproto

        match = self._get_multicast_broadcast_match(network_id)
        self.mod_flow(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _update_multicast_broadcast_flows_for_remote(self, network_id,
                                                     segmentation_id,
                                                     remote_ports):
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

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

            if tunnels.get(tunnel_port) is None:
                tunnels[tunnel_port] = tunnel_port
                actions.append(parser.OFPActionSetField(
                    tunel_id_nxm=segmentation_id))
                actions.append(parser.OFPActionOutput(port=tunnel_port))

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            datapath=datapath,
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=ofproto.OFPFC_MODIFY,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _add_multicast_broadcast_handling_for_remote_port(self,
                                                          lport_id,
                                                          port_key,
                                                          network_id,
                                                          segmentation_id,
                                                          ofport):
        LOG.info(_LI("Adding multicast and broadcast for remote port."))
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        command = ofproto.OFPFC_MODIFY

        network = self.local_networks.get(network_id)
        if network is None:
            network = {
                'remote': {}
            }
            self.local_networks[network_id] = network
            command = ofproto.OFPFC_ADD

        remote_ports = network.get('remote')
        if remote_ports is None:
            remote_ports = {}
            network['remote'] = remote_ports
            command = ofproto.OFPFC_ADD
        remote_ports[lport_id] = port_key

        match = self._get_multicast_broadcast_match(network_id)
        actions = [parser.OFPActionSetField(tunnel_id_nxm=segmentation_id),
                   parser.OFPActionOutput(port=ofport)]

        tunnels = {ofport}

        # todo
        # aggregate  remote tunnel
        for port_id_in_network in remote_ports:
            lport = self.db_store.get_port(self, port_id_in_network)
            if lport is None:
                continue
            tunnel_port = lport.get_external_value('ofport')

            if tunnel_port not in tunnels:
                tunnels.add(tunnel_port)
                actions.append(parser.OFPActionSetField(
                    tunel_id_nxm=segmentation_id))
                actions.append(parser.OFPActionOutput(port=tunnel_port))

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        self.mod_flow(
            datapath=datapath,
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=command,
            priority=const.PRIORITY_LOW,
            match=match)

    def remove_logical_switch(self, lswitch):
        datapath = self.get_datapath()
        ofproto = datapath.ofproto

        network_id = self.db_store.get_network_id(
            lswitch.get_id(),
        )
        match = self._get_multicast_broadcast_match(network_id)

        self.mod_flow(
            datapath=datapath,
            table_id=const.L2_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
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

        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

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
        actions = [parser.OFPActionSetField(reg7=port_key)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(goto_table)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath=datapath,
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=priority,
            match=match)

        self._add_arp_responder(lport)

        if network_type == 'vlan':
            return

        match = parser.OFPMatch(reg7=port_key)
        actions = [parser.OFPActionSetField(tunnel_id_nxm=segmentation_id),
                  parser.OFPActionOutput(port=ofport)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            datapath=datapath,
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        self._add_multicast_broadcast_handling_for_remote_port(lport_id,
                                                               port_key,
                                                               network_id,
                                                               segmentation_id,
                                                               ofport)

    def _install_network_flows_on_first_port_up(self,
                                                segmentation_id,
                                                network_type,
                                                local_network_id):
        LOG.info(_LI('Install network flows on first port up.'))
        network = self.local_networks.get(local_network_id)
        if network:
            local_ports = network.get('local')
            if local_ports:
                return

        if network_type == 'vlan':
            self._install_network_flows_for_vlan(segmentation_id,
                                                 local_network_id)
        else:
            self._install_network_flows_for_tunnel(segmentation_id,
                                               local_network_id)

    """
    Install Ingress network flow for vxlan
    Table=INGRESS_CLASSIFICATION_DISPATCH_TABLE, priority=Medium
    Match: tunnel_id= vni
    Actions: metadata=network_id, goto:INGRESS_DESTIANTION_PORT_LOOKUP_TABLE
    """
    def _install_network_flows_for_tunnel(self, segmentation_id,
                                          local_network_id):
        LOG.debug('Install network flows on first tunnel port up .')
        if segmentation_id is None:
            return
        LOG.info(_LI("Segmentation_id  = %s"), str(segmentation_id))

        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch(tunnel_id_nxm=segmentation_id)

        actions = [parser.OFPActionSetField(metadata=local_network_id)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath=datapath,
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    """
    Install network flows for vlan
    """
    def _install_network_flows_for_vlan(self, segmentation_id,
                                        local_network_id):
        LOG.info(_LI("Install network flows on first vlan up"))

        # L2_LOOKUP for Remote ports
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()

        addint = haddr_to_bin('00:00:00:00:00:00')
        add_mask_int = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, add_mask_int)
        match.set_metadata(local_network_id)
        inst = [parser.OFPInstructionGotoTable(const.EGRESS_TABLE)]
        self.mod_flow(
            datapath=datapath,
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
            datapath=datapath,
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

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
            datapath=datapath,
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _del_network_flows_for_vlan(self, segmentation_id):
        LOG.info(_LI("Delete network flows for vlan"))
        if segmentation_id is None:
            return

        datapath = self.get_datapath()
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        match.set_vlan_vid(segmentation_id)
        self.mod_flow(
            datapath=datapath,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _get_multicast_broadcast_match(self, network_id):
        match = self.get_datapath().\
            ofproto_parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        match.set_metadata(network_id)
        return match
