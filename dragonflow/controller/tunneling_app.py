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

from dragonflow.controller.common.logical_networks import LogicalNetworks
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from oslo_log import log
from ryu.lib.mac import haddr_to_bin

LOG = log.getLogger(__name__)
BUM_MAC = '01:00:00:00:00:00'


class TunnelingApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(TunnelingApp, self).__init__(*args, **kwargs)
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.initalize_tunnel_types()
        self.local_networks = LogicalNetworks()

    def initalize_tunnel_types(self):
        if cfg.CONF.df.tunnel_types:
            self.tunnel_types = cfg.CONF.df.tunnel_types
        else:
            self.tunnel_types = [cfg.CONF.df.tunnel_type]

    def add_local_port(self, lport):
        network_type = lport.get_external_value('network_type')
        if network_type not in self.tunnel_types:
            return
        network_id = lport.get_external_value('local_network_id')

        port_count = self.local_networks.get_local_port_count(
                network_id=network_id,
                network_type=network_type)
        if port_count == 0:
            self._new_network_flow(lport,
                                   network_id,
                                   network_type)

        self.local_networks.add_local_port(port_id=lport.get_id(),
                                           network_id=network_id,
                                           network_type=network_type)

    def remove_local_port(self, lport):
        network_type = lport.get_external_value('network_type')
        if network_type not in self.tunnel_types:
            return
        network_id = lport.get_external_value('local_network_id')
        self.local_networks.remove_local_port(port_id=lport.get_id(),
                                              network_id=network_id,
                                              network_type=network_type)
        port_count = self.local_networks.get_local_port_count(
                network_id=network_id,
                network_type=network_type)
        if port_count == 0:
            self._remove_network_flow(lport, network_id, network_type)

    def _new_network_flow(self, lport, network_id, network_type):
        match = self._make_network_match(lport, network_id, network_type)
        actions = [self.parser.OFPActionSetField(metadata=network_id)]
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = self.parser.OFPInstructionGotoTable(
            const.L2_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath=self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_network_flow(self, lport, network_id, network_type):
        match = self._make_network_match(lport, network_id, network_type)
        self.mod_flow(
                datapath=self.get_datapath(),
                command=self.ofproto.OFPFC_DELETE,
                table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                priority=const.PRIORITY_LOW,
                match=match)

    def _make_network_match(self, lport, network_id, network_type):
        segmentation_id = lport.get_external_value('segmentation_id')
        ofport = self.vswitch_api.get_vtp_ofport(network_type)
        return self.parser.OFPMatch(tunnel_id_nxm=segmentation_id,
                                    in_port=ofport)

    def add_remote_port(self, lport):
        if self.get_datapath() is None:
            return
        network_type = lport.get_external_value('network_type')
        if network_type not in self.tunnel_types:
            return
        segmentation_id = lport.get_external_value('segmentation_id')
        self._add_egress_dispatch_flow(lport, segmentation_id)
        network_id = lport.get_external_value('local_network_id')
        self.local_networks.add_remote_port(port_id=lport.get_id(),
                                           network_id=network_id,
                                           network_type=network_type)
        self._modify_egress_bum_flow(network_id,
                                     network_type,
                                     segmentation_id,
                                     self.ofproto.OFPFC_ADD)

    def remove_remote_port(self, lport):
        network_type = lport.get_external_value('network_type')
        if network_type not in self.tunnel_types:
            return
        self._remove_egress_dispatch_flow(lport)
        network_id = lport.get_external_value('local_network_id')
        segmentation_id = lport.get_external_value('segmentation_id')
        self.local_networks.remove_remote_port(port_id=lport.get_id(),
                                           network_id=network_id,
                                           network_type=network_type)
        self._modify_egress_bum_flow(network_id,
                                     network_type,
                                     segmentation_id,
                                     self.ofproto.OFPFC_MODIFY)

    def _add_egress_dispatch_flow(self, lport, segmentation_id):
        remote_ip = lport.get_external_value('peer_vtep_address')
        ofport = lport.get_external_value('ofport')
        match = self.parser.OFPMatch(reg7=lport.get_unique_key())
        actions = [
                self.parser.OFPActionSetField(tun_ipv4_dst=remote_ip),
                self.parser.OFPActionSetField(tunnel_id_nxm=segmentation_id),
                self.parser.OFPActionOutput(port=ofport)]
        ofproto = self.get_datapath().ofproto
        action_inst = self.parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            datapath=self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_egress_dispatch_flow(self, lport):
        match = self.parser.OFPMatch(reg7=lport.get_unique_key())
        self.mod_flow(
            datapath=self.get_datapath(),
            command=self.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _modify_egress_bum_flow(self,
                               network_id,
                               network_type,
                               segmentation_id,
                               command):
        match = self._make_bum_match(metadata=network_id)
        port_count = self.local_networks.get_remote_port_count(
                network_id=network_id,
                network_type=network_type)
        while True:
            if port_count == 0:
                inst = None
                command = self.ofproto.OFPFC_DELETE
                break
            if port_count != 1:
                command = self.ofproto.OFPFC_MODIFY
            actions = self._make_bum_flow_actions(network_id, segmentation_id)
            inst = [self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, actions)]
            break

        self.mod_flow(
            datapath=self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=command,
            priority=const.PRIORITY_LOW,
            match=match)

    def _make_bum_match(self, **kargs):
        match = self.parser.OFPMatch(**kargs)
        bum_addr = haddr_to_bin(BUM_MAC)
        match.set_dl_dst_masked(bum_addr, bum_addr)
        return match

    def _make_bum_flow_actions(self, network_id, segmentation_id):
        remote_ports = self.local_networks.get_remote_ports(
                network_id=network_id)
        actions = list()
        for port_id in remote_ports:
            lport = self.db_store.get_port(port_id)
            if not lport:
                continue
            peer_ip = lport.get_external_value('peer_vtep_address')
            ofport = lport.get_external_value('ofport')
            ofpact_set_field = self.parser.OFPActionSetField
            actions += [
                    ofpact_set_field(tun_ipv4_dst=peer_ip),
                    ofpact_set_field(tunnel_id_nxm=segmentation_id),
                    ofpact_set_field(port=ofport)]
        return actions
