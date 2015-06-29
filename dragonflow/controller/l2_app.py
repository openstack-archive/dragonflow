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

import threading

from ryu.base import app_manager
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.lib.mac import haddr_to_bin
from ryu.ofproto import ofproto_v1_3

from oslo_log import log

from neutron.i18n import _LI


LOG = log.getLogger(__name__)

# TODO(gsagie) currently the number set in Ryu for this
# (OFPP_IN_PORT) is not working, use this until resolved
OF_IN_PORT = 0xfff8


class L2App(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, *args, **kwargs):
        super(L2App, self).__init__(*args, **kwargs)
        self.dp = None
        self.local_ports = {}
        self.remote_ports = {}
        self.local_networks = {}
        self.db_lock = threading.Lock()

    def start(self):
        super(L2App, self).start()
        return 1

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        self.dp = ev.msg.datapath
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

    def _create_port_dict(self, lport_id, mac, network_id, ofport,
                          tunnel_key, is_local):
        port = {'lport_id': lport_id,
                'mac': mac,
                'network_id': network_id,
                'ofport': ofport,
                'tunnel_key': tunnel_key,
                'is_local': is_local}
        return port

    def add_local_port(self, lport_id, mac, network_id, ofport, tunnel_key):

        if self.dp is None:
            return

        port = self._create_port_dict(lport_id, mac, network_id, ofport,
                                      tunnel_key, True)
        cached_port_data = self.local_ports.get(lport_id)
        if cached_port_data is None or port != cached_port_data:
            with self.db_lock:
                self.local_ports[lport_id] = port
            self._add_local_port(lport_id, mac, network_id, ofport, tunnel_key)

    def _add_local_port(self, lport_id, mac, network_id, ofport, tunnel_key):

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

        goto_inst = parser.OFPInstructionGotoTable(17)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=0,
            priority=100,
            match=match)

        # Dispatch to local port according to unique tunnel_id
        parser = self.dp.ofproto_parser
        ofproto = self.dp.ofproto
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
            table_id=0,
            priority=100,
            match=match)

        # Destination classifier for port
        match = parser.OFPMatch()
        match.set_metadata(network_id)
        match.set_dl_dst(haddr_to_bin(mac))
        actions = []
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(64)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=17,
            priority=100,
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
            table_id=64,
            priority=100,
            match=match)

        self._add_multicast_broadcast_handling(network_id, lport_id,
                                               tunnel_key)

    def _add_multicast_broadcast_handling(self, network_id,
                                          lport_id, tunnel_key):

        if self.dp is None:
            return
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
            actions.append(parser.NXActionResubmitTable(OF_IN_PORT, 64))

        inst = [self.dp.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=17,
            command=command,
            priority=200,
            match=match)

    def add_remote_port(self, lport_id, mac, network_id, ofport, tunnel_key):

        if self.dp is None:
            return

        port = self._create_port_dict(lport_id, mac, network_id, ofport,
                                      tunnel_key, False)
        cached_port_data = self.remote_ports.get(lport_id)
        if cached_port_data is None or port != cached_port_data:
            with self.db_lock:
                self.remote_ports[lport_id] = port
            self._add_remote_port(lport_id, mac, network_id, ofport,
                                  tunnel_key)

    def _add_remote_port(self, lport_id, mac, network_id, ofport, tunnel_key):

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
        goto_inst = parser.OFPInstructionGotoTable(64)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.dp,
            inst=inst,
            table_id=17,
            priority=100,
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
            table_id=64,
            priority=100,
            match=match)

        self._add_multicast_broadcast_handling(network_id, lport_id,
                                               tunnel_key)

    def _install_flows_on_switch_up(self):
        # Clear local networks cache so the multicast/broadcast flows
        # are installed correctly
        self.local_networks.clear()
        with self.db_lock:
            for port in self.local_ports.values():
                self._add_local_port(port['lport_id'],
                                     port['mac'],
                                     port['network_id'],
                                     port['ofport'],
                                     port['tunnel_key'])

            for port in self.remote_ports.values():
                self._add_remote_port(port['lport_id'],
                                      port['mac'],
                                      port['network_id'],
                                      port['ofport'],
                                      port['tunnel_key'])

    # TODO(gsagie) extract this common method (used both by L2/L3 apps)
    def mod_flow(self, datapath, cookie=0, cookie_mask=0, table_id=0,
                 command=None, idle_timeout=0, hard_timeout=0,
                 priority=0xff, buffer_id=0xffffffff, match=None,
                 actions=None, inst_type=None, out_port=None,
                 out_group=None, flags=0, inst=None):

        if command is None:
            command = datapath.ofproto.OFPFC_ADD

        if inst is None:
            if inst_type is None:
                inst_type = datapath.ofproto.OFPIT_APPLY_ACTIONS

            inst = []
            if actions is not None:
                inst = [datapath.ofproto_parser.OFPInstructionActions(
                    inst_type, actions)]

                if match is None:
                    match = datapath.ofproto_parser.OFPMatch()

        if out_port is None:
            out_port = datapath.ofproto.OFPP_ANY

        if out_group is None:
            out_group = datapath.ofproto.OFPG_ANY

        message = datapath.ofproto_parser.OFPFlowMod(datapath, cookie,
                                                     cookie_mask,
                                                     table_id, command,
                                                     idle_timeout,
                                                     hard_timeout,
                                                     priority,
                                                     buffer_id,
                                                     out_port,
                                                     out_group,
                                                     flags,
                                                     match,
                                                     inst)

        datapath.send_msg(message)
