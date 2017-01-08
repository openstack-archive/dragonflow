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

import collections

import netaddr
from oslo_config import cfg
from oslo_log import log
from ryu.ofproto import ether
from ryu.ofproto import nicira_ext

from dragonflow._i18n import _
from dragonflow._i18n import _LW, _LI

from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app


LOG = log.getLogger(__name__)

DF_SNAT_APP_OPTS = [
    cfg.StrOpt('external_network_bridge',
              default='br-ex',
              help=_("Name of bridge used for external network traffic")),
    cfg.StrOpt('int_peer_patch_port', default='patch-ex',
               help=_("Peer patch port in integration bridge for external "
                      "bridge.")),
    cfg.StrOpt('ex_peer_patch_port', default='patch-int',
               help=_("Peer patch port in external bridge for integration "
                      "bridge.")),
    cfg.StrOpt('host_ip',
               default='172.100.0.4',
               help=_("Compute node external IP")),
]

FIP_GW_RESOLVING_STATUS = 'resolving'


class SNATApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        LOG.warning(_LW("Loading SNAT application ... "))
        super(SNATApp, self).__init__(*args, **kwargs)
        cfg.CONF.register_opts(DF_SNAT_APP_OPTS, group='df_snat_app')
        self.external_network_bridge = \
            cfg.CONF.df_snat_app.external_network_bridge
        self.external_bridge_mac = "00:00:00:00:00:00"
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.int_peer_patch_port = cfg.CONF.df_snat_app.int_peer_patch_port
        self.ex_peer_patch_port = cfg.CONF.df_snat_app.ex_peer_patch_port
        self.external_networks = collections.defaultdict(int)
        # new application configuration
        self.host_ip = cfg.CONF.df_snat_app.host_ip
        self.host_mac = "91:92:93:94:95:96"
        self.chassis = None
        # next parameter counts number of connected compute ports
        self.count = 0

    def switch_features_handler(self, ev):
        self._init_external_bridge()
        self._install_output_to_physical_patch(self.external_ofport)
        # set correct mac address on update
        self._install_arp_responder()

    def ovs_port_updated(self, ovs_port):
        if ovs_port.get_name() != self.external_network_bridge:
            return

        LOG.info(_LI("Ex. Bridge port update is called ... "))
        mac = ovs_port.get_mac_in_use()
        if (self.external_bridge_mac == mac
                or not mac
                or mac == '00:00:00:00:00:00'):
            return

        self.external_bridge_mac = mac

        if self.chassis is None:
            return

        # set correct mac address on update
        if self.count > 0:
            self._install_snat_egress_after_conntrack()

    def _init_external_bridge(self):
        if not self.vswitch_api.patch_port_exist(self.ex_peer_patch_port):
            self.external_ofport = self.vswitch_api.create_patch_port(
                self.integration_bridge,
                self.ex_peer_patch_port,
                self.int_peer_patch_port)
            self.vswitch_api.create_patch_port(
                self.external_network_bridge,
                self.int_peer_patch_port,
                self.ex_peer_patch_port)
        else:
            self.external_ofport = self.vswitch_api.get_port_ofport(
                self.ex_peer_patch_port)

    def _install_output_to_physical_patch(self, ofport):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        actions = [parser.OFPActionOutput(ofport,
                                          ofproto.OFPCML_NO_BUFFER)]
        actions_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [actions_inst]
        self.mod_flow(self.get_datapath(), inst=inst,
                      table_id=const.EGRESS_EXTERNAL_TABLE,
                      priority=const.PRIORITY_MEDIUM, match=None)

    def _install_arp_responder(self):
        # install host arp responder flow rules
        if netaddr.IPAddress(self.host_ip).version != 4:
            return
        arp_responder.ArpResponder(self,
             None,
             self.host_ip,
             self.host_mac,
             const.INGRESS_NAT_TABLE).add()

    def _remove_snat_ingress(self):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        match = parser.OFPMatch()
        match.set_in_port(self.external_ofport)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_DEFAULT,
            cookie=const.NAT_TRACKING_ZONE,
            match=match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _remove_snat_egress(self):

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_LOW,
            cookie=0x0,
            match=match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def remove_local_port(self, lport):
        LOG.info(_LI("SNAT application: remove local port %(lport)s"),
                 {'lport': lport})

        # verify and update connected compute port amount
        if lport.get_device_owner().startswith("compute"):
            self.count -= 1

        # remove SNAT related flows only on last VM port removal
        if (self.count == 0):
            self._remove_snat_egress()
            self._remove_snat_ingress()

    def add_local_port(self, lport):
        LOG.info(_LI("SNAT application: add local port  %(lport)s"),
                {'lport': lport})

        # install flows only when compute port is added
        if lport.get_device_owner().startswith('compute'):
            self.chassis = lport.get_chassis()
            # install flows only on first port add
            # flows are agnostic of port amount and tenant id
            if(self.count == 0):
                self. _install_snat_ingress(lport)
                self. _install_snat_egress(lport)
                # update connected VM amount
                self.count += 1
        else:
            LOG.info(_LI('SNAT application: not a compute port, skipped'))

    def _install_snat_ingress(self, lport):
        """
        Ingress SNAT management requires 3 flows:
            table 0:    in_port=patch_ex -> table: 15
            table 15:  connection tracking + reverse nat -> table: 16
            table 16:  set L2 correct addresses -> table: 78
        """
        self._install_ingress_goto_rules()
        self._install_snat_ingress_conntrack()
        self._install_snat_ingress_after_conntrack(lport.get_mac())

    def _install_snat_egress(self, lport):
        """
        Egress SNAT management requires 3 flows:
            table 20:    in_port=vm_port -> table: 30
            table 30:  connection tracking + nat -> table: 31
            table 31:  set L2 correct addresses -> table: 66
        """
        self._install_egress_goto_rules()
        self._install_snat_egress_conntrack()
        self._install_snat_egress_after_conntrack()

    def _install_egress_goto_rules(self):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.get_datapath().ofproto
        actions = [
            parser.NXActionRegLoad(
                ofs_nbits=nicira_ext.ofs_nbits(0, 15),
                dst='reg0',
                value=const.NAT_TRACKING_ZONE)
                   ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_NAT_TABLE)

        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=0x0,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_ingress_goto_rules(self):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_in_port(self.external_ofport)

        ofproto = self.get_datapath().ofproto
        actions = [
            parser.NXActionRegLoad(
                ofs_nbits=nicira_ext.ofs_nbits(0, 15),
                dst='reg0',
                value=const.NAT_TRACKING_ZONE)
                   ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.INGRESS_NAT_TABLE)

        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=const.NAT_TRACKING_ZONE,
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_DEFAULT,
            match=match)

    def _install_snat_egress_conntrack(self):
        LOG.info(_LI('SNAT application: install egress'))
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.get_datapath().ofproto

        actions = [
            parser.NXActionRegMove(
                                src_field='ipv4_src',
                                dst_field='reg5',
                                n_bits=32),
            parser.NXActionRegMove(
                                src_field='reg6',
                                dst_field='ipv4_src',
                                n_bits=32),
            parser.NXActionRegLoad(
                                ofs_nbits=nicira_ext.ofs_nbits(31, 31),
                                dst="ipv4_src",
                                value=1,)
                   ]
        actions += [
            parser.NXActionCT(
                                     alg=0,
                                     flags=const.CT_FLAG_COMMIT,
                                     recirc_table=const.EGRESS_NAT2_TABLE,
                                     zone_ofs_nbits=15,
                                     zone_src='reg0',
                                     actions=[
                                            parser.NXActionNAT(
                                                flags=const.CT_FLAG_COMMIT,
                                                range_ipv4_min=self.host_ip,
                                                range_ipv4_max=self.host_ip,
                                                    ),
                                            parser.NXActionRegMove(
                                                dst_field='ct_mark',
                                                src_field='reg5',
                                                n_bits=32),
                                              ]
                              )
                    ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        inst = [action_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=0x0,
            inst=inst,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_egress_after_conntrack(self):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.get_datapath().ofproto
        actions = [
            parser.OFPActionSetField(eth_src=self.host_mac),
            parser.OFPActionSetField(eth_dst=self.external_bridge_mac)
                ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_EXTERNAL_TABLE)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=0x0,
            inst=inst,
            table_id=const.EGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_ingress_conntrack(self):
        LOG.info(_LI('SNAT application: install ingress'))

        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.get_datapath().ofproto
        actions = [
            parser.NXActionCT(
                                     alg=0,
                                     flags=0,
                                     recirc_table=const.INGRESS_NAT2_TABLE,
                                     zone_ofs_nbits=15,
                                     zone_src='reg0',
                                     actions=[
                                         parser.NXActionNAT(flags=0)
                                            ]
                              )
                   ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=0x0,
            inst=inst,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_ingress_after_conntrack(self, vm_mac):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.get_datapath().ofproto

        actions = [
            parser.OFPActionSetField(eth_src=self.host_mac),
            parser.OFPActionSetField(eth_dst=vm_mac)
                    ]

        actions += [
            parser.NXActionRegLoad(
                                            ofs_nbits=nicira_ext.ofs_nbits(
                                                31, 31),
                                            dst="ipv4_dst",
                                            value=0,)
                    ]
        actions += [
            parser.NXActionRegMove(
                                            src_field='ipv4_dst',
                                            dst_field='reg7',
                                            n_bits=32)
                   ]
        actions += [
            parser.NXActionRegMove(
                                            src_field='ct_mark',
                                            dst_field='ipv4_dst',
                                            n_bits=32)
                   ]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_DISPATCH_TABLE)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=0x0,
            inst=inst,
            table_id=const.INGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)
