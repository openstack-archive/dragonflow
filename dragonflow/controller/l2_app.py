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

from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.lib.mac import haddr_to_bin
from ryu.ofproto import ofproto_v1_3

from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp

from oslo_log import log

from neutron.i18n import _LI


LOG = log.getLogger(__name__)

# TODO(gsagie) currently the number set in Ryu for this
# (OFPP_IN_PORT) is not working, use this until resolved
OF_IN_PORT = 0xfff8


class L2App(DFlowApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(L2App, self).__init__(*args, **kwargs)
        self.dp = None
        self.local_networks = {}
        self.db_store = kwargs['db_store']

    def start(self):
        super(L2App, self).start()
        return 1

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        self.dp = ev.msg.datapath
        self.add_flow_go_to_table(self.dp,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)
        self.add_flow_go_to_table(self.dp, const.ARP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.L2_LOOKUP_TABLE)

        # ARP traffic => send to ARP table
        match = self.dp.ofproto_parser.OFPMatch(eth_type=0x0806)
        self.add_flow_go_to_table(self.dp,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  const.PRIORITY_MEDIUM,
                                  const.ARP_TABLE, match=match)
        self._install_flows_on_switch_up()
        self.send_port_desc_stats_request(self.dp)

    def send_port_desc_stats_request(self, datapath):
        ofp_parser = datapath.ofproto_parser
        req = ofp_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status_handler(self, ev):
        msg = ev.msg
        reason = msg.reason
        port_no = msg.desc.port_no
        datapath = ev.msg.datapath

        ofproto = msg.datapath.ofproto
        if reason == ofproto.OFPPR_ADD:
            LOG.info(_LI("port added %s"), port_no)
        elif reason == ofproto.OFPPR_DELETE:
            LOG.info(_LI("port deleted %s"), port_no)
        elif reason == ofproto.OFPPR_MODIFY:
            LOG.info(_LI("port modified %s"), port_no)
        else:
            LOG.info(_LI("Illeagal port state %(port_no)s %(reason)s")
                     % {'port_no': port_no, 'reason': reason})
        LOG.info(_LI(" Updating flow table on agents got port update "))
        if self.dp:
            self.send_port_desc_stats_request(datapath)
            if reason == ofproto.OFPPR_DELETE:
                pass

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        pass
        # datapath = ev.msg.datapath
        # for port in ev.msg.body:
        #     if port.name.startswith('df-'):
        #         print 'tunnel port detected'
        #     elif port.name.startswith('tap'):
        #         print 'VM port detected'

    def remove_local_port(self, lport_id, mac, network_id, ofport, tunnel_key):
        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        # Remove ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        msg = parser.OFPFlowMod(
            datapath=self.dp,
            cookie=0,
            cookie_mask=0,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)
        self.dp.send_msg(msg)

        # Remove dispatch to local port according to unique tunnel_id
        match = parser.OFPMatch(tunnel_id_nxm=tunnel_key)
        msg = parser.OFPFlowMod(
            datapath=self.dp,
            cookie=0,
            cookie_mask=0,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)
        self.dp.send_msg(msg)

        # Remove destination classifier for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        msg = parser.OFPFlowMod(datapath=self.dp,
                                cookie=0,
                                cookie_mask=0,
                                table_id=const.L2_LOOKUP_TABLE,
                                command=ofproto.OFPFC_DELETE,
                                priority=const.PRIORITY_MEDIUM,
                                out_port=ofproto.OFPP_ANY,
                                out_group=ofproto.OFPG_ANY,
                                match=match)
        self.dp.send_msg(msg)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        msg = parser.OFPFlowMod(datapath=self.dp,
                                cookie=0,
                                cookie_mask=0,
                                table_id=const.EGRESS_TABLE,
                                command=ofproto.OFPFC_DELETE,
                                priority=const.PRIORITY_MEDIUM,
                                out_port=ofproto.OFPP_ANY,
                                out_group=ofproto.OFPG_ANY,
                                match=match)
        self.dp.send_msg(msg)

        self._del_multicast_broadcast_handling_for_port(network_id, lport_id)

    def remove_remote_port(self, lport_id, mac, network_id, tunnel_key):

        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        # Remove destination classifier for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        msg = parser.OFPFlowMod(datapath=self.dp,
                                cookie=0,
                                cookie_mask=0,
                                table_id=const.L2_LOOKUP_TABLE,
                                command=ofproto.OFPFC_DELETE,
                                priority=const.PRIORITY_MEDIUM,
                                out_port=ofproto.OFPP_ANY,
                                out_group=ofproto.OFPG_ANY,
                                match=match)
        self.dp.send_msg(msg)

        # Remove egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        msg = parser.OFPFlowMod(datapath=self.dp,
                                cookie=0,
                                cookie_mask=0,
                                table_id=const.EGRESS_TABLE,
                                command=ofproto.OFPFC_DELETE,
                                priority=const.PRIORITY_MEDIUM,
                                out_port=ofproto.OFPP_ANY,
                                out_group=ofproto.OFPG_ANY,
                                match=match)
        self.dp.send_msg(msg)

        self._del_multicast_broadcast_handling_for_port(network_id, lport_id)

    def add_local_port(self, lport_id, mac, network_id, ofport, tunnel_key):

        if self.dp is None:
            return

        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        # Ingress classifier for port
        match = parser.OFPMatch()
        match.set_in_port(ofport)
        actions = []
        actions.append(parser.OFPActionSetField(reg6=tunnel_key))
        actions.append(parser.OFPActionSetField(metadata=network_id))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(
            const.SERVICES_CLASSIFICATION_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Dispatch to local port according to unique tunnel_id
        match = parser.OFPMatch(tunnel_id_nxm=tunnel_key)
        actions = []
        actions.append(parser.OFPActionOutput(ofport,
                                              ofproto.OFPCML_NO_BUFFER))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Destination classifier for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = []
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        actions = [parser.OFPActionOutput(port=ofport)]
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._add_multicast_broadcast_handling_for_port(network_id, lport_id,
                                                        tunnel_key)

    def _del_multicast_broadcast_handling_for_port(self, network_id,
                                                   lport_id):
        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        command = self.dp.ofproto.OFPFC_MODIFY
        network = self.local_networks.get(network_id)
        if network is None:
            # TODO(gsagie) add error here
            return

        # TODO(gsagie) check if lport in network structure?
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

        inst = [self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _add_multicast_broadcast_handling_for_port(self, network_id,
                                                   lport_id, tunnel_key):
        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        command = self.dp.ofproto.OFPFC_MODIFY
        network = self.local_networks.get(network_id)
        if network is None:
            network = {}
            self.local_networks[network_id] = network
            command = self.dp.ofproto.OFPFC_ADD

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

        inst = [self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            command=command,
            priority=const.PRIORITY_HIGH,
            match=match)

    def add_remote_port(self, lport_id, mac, network_id, ofport, tunnel_key):

        if self.dp is None:
            return

        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto

        # Destination classifier for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = []
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # Egress classifier for port
        match = parser.OFPMatch(reg7=tunnel_key)
        actions = []
        actions.append(parser.OFPActionSetField(tunnel_id_nxm=tunnel_key))
        actions.append(parser.OFPActionOutput(port=ofport))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        self._add_multicast_broadcast_handling_for_port(network_id, lport_id,
                                                        tunnel_key)

    def _install_flows_on_switch_up(self):
        # Clear local networks cache so the multicast/broadcast flows
        # are installed correctly
        self.local_networks.clear()
        for port in self.db_store.get_ports():
            if port.get_external_value('is_local'):
                self.add_local_port(port.get_id(),
                                    port.get_mac(),
                                    port.get_external_value(
                                        'local_network_id'),
                                    port.get_external_value(
                                        'ofport'),
                                    port.get_tunnel_key())
            else:
                self.add_remote_port(port.get_id(),
                                     port.get_mac(),
                                     port.get_external_value(
                                          'local_network_id'),
                                     port.get_external_value(
                                          'ofport'),
                                     port.get_tunnel_key())
