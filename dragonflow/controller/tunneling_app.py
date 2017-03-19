# Copyright (c) 2017 OpenStack Foundation.
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

from oslo_log import log
from ryu.lib import mac as mac_api

from dragonflow._i18n import _LI, _LW
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import logical_networks
from dragonflow.controller import df_base_app
from dragonflow.db.models import l2

LOG = log.getLogger(__name__)


class TunnelingApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(TunnelingApp, self).__init__(*args, **kwargs)
        self.initalize_tunnel_types()
        self.local_networks = logical_networks.LogicalNetworks()

    def initalize_tunnel_types(self):
        # TODO(itamaro) this method should be removed once
        # cfg.CONF.df.tunnel_type is made obsolete.
        if cfg.CONF.df.tunnel_types:
            self.tunnel_types = cfg.CONF.df.tunnel_types
        else:
            self.tunnel_types = [cfg.CONF.df.tunnel_type]

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    def _add_local_port(self, lport):
        network_type = lport.network_type
        if network_type not in self.tunnel_types:
            LOG.warning(_LW("added unsupported network %(net_type)s lport"),
                        {'net_type': network_type})
            return
        network_id = lport.local_network_id
        LOG.info(_LI("adding %(net_type)s lport %(lport)s"),
                 {'net_type': network_type,
                  'lport': lport})
        port_count = self.local_networks.get_local_port_count(
                network_id=network_id,
                network_type=network_type)
        if port_count == 0:
            self._new_network_ingress_flow(lport,
                                           network_id,
                                           network_type)

        self.local_networks.add_local_port(port_id=lport.id,
                                           network_id=network_id,
                                           network_type=network_type)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _remove_local_port(self, lport):
        network_type = lport.network_type
        if network_type not in self.tunnel_types:
            LOG.warning(_LW("removed unsupported network %(net_type)s lport"),
                        {'net_type': network_type})
            return
        network_id = lport.local_network_id
        self.local_networks.remove_local_port(port_id=lport.id,
                                              network_id=network_id,
                                              network_type=network_type)
        port_count = self.local_networks.get_local_port_count(
                network_id=network_id,
                network_type=network_type)
        if port_count == 0:
            self._remove_network_ingress_flow(lport, network_id, network_type)

    def _new_network_ingress_flow(self, lport, network_id, network_type):
        LOG.debug("adding new %(net_type)s network %(network_id)s",
                  {'net_type': network_type,
                   'network_id': network_id})

        match = self._make_network_match(lport, network_id, network_type)
        actions = [self.parser.OFPActionSetField(metadata=network_id)]
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = self.parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_network_ingress_flow(self, lport, network_id, network_type):
        match = self._make_network_match(lport, network_id, network_type)
        self.mod_flow(
                command=self.ofproto.OFPFC_DELETE,
                table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                priority=const.PRIORITY_MEDIUM,
                match=match)

    def _make_network_match(self, lport, network_id, network_type):
        segmentation_id = lport.segmentation_id
        ofport = self.vswitch_api.get_vtp_ofport(network_type)
        return self.parser.OFPMatch(tunnel_id_nxm=segmentation_id,
                                    in_port=ofport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_REMOTE_CREATED)
    def _add_remote_port(self, lport):
        network_type = lport.network_type
        if network_type not in self.tunnel_types:
            return
        segmentation_id = lport.segmentation_id
        self._add_egress_dispatch_flow(lport, segmentation_id)
        network_id = lport.local_network_id
        LOG.info(_LI("adding remote %(net_type)s lport %(lport)s"),
                 {'net_type': network_type,
                  'lport': lport})
        self.local_networks.add_remote_port(port_id=lport.id,
                                            network_id=network_id,
                                            network_type=network_type)
        self._modify_egress_bum_flow(network_id,
                                     network_type,
                                     segmentation_id,
                                     self.ofproto.OFPFC_ADD)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_REMOTE_DELETED)
    def remove_remote_port(self, lport):
        network_type = lport.network_type
        if network_type not in self.tunnel_types:
            return
        self._remove_egress_dispatch_flow(lport)
        network_id = lport.local_network_id
        segmentation_id = lport.segmentation_id
        self.local_networks.remove_remote_port(port_id=lport.id,
                                               network_id=network_id,
                                               network_type=network_type)
        self._modify_egress_bum_flow(network_id,
                                     network_type,
                                     segmentation_id,
                                     self.ofproto.OFPFC_MODIFY)

    def _add_egress_dispatch_flow(self, lport, segmentation_id):
        remote_ip = lport.peer_vtep_address
        ofport = lport.ofport
        LOG.debug("set egress dispatch flow %(seg)s peer %(remote_ip)s",
                  {'seg': segmentation_id,
                   'remote_ip': remote_ip})

        match = self.parser.OFPMatch(reg7=lport.unique_key)
        actions = [
                self.parser.OFPActionSetField(tun_ipv4_dst=remote_ip),
                self.parser.OFPActionSetField(tunnel_id_nxm=segmentation_id),
                self.parser.OFPActionOutput(port=ofport)]
        ofproto = self.ofproto
        action_inst = self.parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_egress_dispatch_flow(self, lport):
        match = self.parser.OFPMatch(reg7=lport.unique_key)
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _eval_flow_actions(self, network_id, segmentation_id,
                           port_count, command):
        inst = None
        if port_count == 0:
            # override command to delete as it is the last port for network
            command = self.ofproto.OFPFC_DELETE
        else:
            if port_count != 1:
                # when there are more then 1 ports in network modify
                command = self.ofproto.OFPFC_MODIFY
            # use the command provided by higher level call as
            # the mod_flow command
            actions = self._make_bum_flow_actions(network_id, segmentation_id)
            inst = [self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return inst, command

    def _modify_egress_bum_flow(self,
                                network_id,
                                network_type,
                                segmentation_id,
                                command):
        match = self._make_bum_match(metadata=network_id)
        port_count = self.local_networks.get_remote_port_count(
                network_id=network_id,
                network_type=network_type)
        inst, command = self._eval_flow_actions(
                network_id, segmentation_id, port_count, command)
        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_TABLE,
            command=command,
            priority=const.PRIORITY_LOW,
            match=match)

    def _make_bum_match(self, **kwargs):
        match = self.parser.OFPMatch(**kwargs)
        bum_addr = mac_api.haddr_to_bin(mac_api.UNICAST)
        match.set_dl_dst_masked(bum_addr, bum_addr)
        return match

    def _make_bum_flow_actions(self, network_id, segmentation_id):
        remote_ports = self.local_networks.get_remote_ports(
                network_id=network_id)
        actions = []
        peer_ip_list = set()
        for port_id in remote_ports:
            lport = self.db_store2.get_one(l2.LogicalPort(id=port_id))
            if not lport:
                continue
            peer_ip = lport.peer_vtep_address
            if peer_ip in peer_ip_list:
                continue
            peer_ip_list.add(peer_ip)
            ofport = lport.ofport
            ofpact_set_field = self.parser.OFPActionSetField
            actions += [
                    ofpact_set_field(tun_ipv4_dst=peer_ip),
                    ofpact_set_field(tunnel_id_nxm=segmentation_id),
                    self.parser.OFPActionOutput(port=ofport)]
        return actions
