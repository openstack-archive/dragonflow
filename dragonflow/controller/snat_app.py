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

import collections

import netaddr
from oslo_config import cfg
from oslo_log import log
from ryu.ofproto import ether
from ryu.ofproto import nicira_ext

from dragonflow._i18n import _LI

from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app

LOG = log.getLogger(__name__)


class SNATApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        LOG.info(_LI("Loading SNAT application ... "))
        super(SNATApp, self).__init__(*args, **kwargs)
        self.external_network_bridge = \
            cfg.CONF.df_snat_app.external_network_bridge
        self.external_bridge_mac = const.EMPTY_MAC
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.int_peer_patch_port = cfg.CONF.df_snat_app.int_peer_patch_port
        self.ex_peer_patch_port = cfg.CONF.df_snat_app.ex_peer_patch_port
        self.external_networks = collections.defaultdict(int)
        # new application configuration
        self.external_host_ip = cfg.CONF.df_snat_app.external_host_ip
        self.external_host_mac = cfg.CONF.df_snat_app.external_host_mac
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
                or mac == const.EMPTY_MAC):
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
        if netaddr.IPAddress(self.external_host_ip).version != 4:
            return
        arp_responder.ArpResponder(self,
             None,
             self.external_host_ip,
             self.external_host_mac,
             const.INGRESS_NAT_TABLE).add()

    def _remove_snat_ingress(self):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        #match = parser.OFPMatch(in_port=self.external_ofport)
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_DEFAULT,
            match=match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _remove_snat_ingress_after_conntrack(self, vm_ip):

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ct_mark=int(netaddr.IPAddress(vm_ip)))

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
            priority=const.PRIORITY_MEDIUM_LOW,
            match=match)

        self.mod_flow(
            self.get_datapath(),
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

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
                self._remove_snat_ingress()
                self._remove_snat_egress()

            self._remove_snat_ingress_after_conntrack(lport.get_ip())
        else:
            LOG.info(_LI('SNAT application: not a compute port, skipped'))

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

            # instance specific flow
            self._install_snat_ingress_after_conntrack(lport.get_ip(),
                                                       lport.get_mac())

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

        self.add_flow_go_to_table(self.get_datapath(),
            const.L3_LOOKUP_TABLE,
            const.PRIORITY_MEDIUM_LOW,
            const.EGRESS_NAT_TABLE,
            match=match)

    def _install_ingress_goto_rules(self):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch()
        match.set_in_port(self.external_ofport)

        self.add_flow_go_to_table(self.get_datapath(),
            const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            const.PRIORITY_DEFAULT,
            const.INGRESS_NAT_TABLE,
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
                             zone_ofs_nbits=const.NAT_TRACKING_ZONE,
                             zone_src='',
                             actions=[
                                    parser.NXActionNAT(
                                        flags=const.CT_FLAG_COMMIT,
                                        range_ipv4_min=self.external_host_ip,
                                        range_ipv4_max=self.external_host_ip,
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
            inst=inst,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_egress_after_conntrack(self):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.get_datapath().ofproto
        actions = [
            parser.OFPActionSetField(eth_src=self.external_host_mac),
            parser.OFPActionSetField(eth_dst=self.external_bridge_mac)
                ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_EXTERNAL_TABLE)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_ingress_conntrack(self):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.get_datapath().ofproto
        actions = [
            parser.NXActionCT(
                     alg=0,
                     flags=0,
                     recirc_table=const.INGRESS_NAT2_TABLE,
                     zone_ofs_nbits=const.NAT_TRACKING_ZONE,
                     zone_src='',
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
            inst=inst,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_ingress_after_conntrack(self, vm_ip, vm_mac):
        parser = self.get_datapath().ofproto_parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ct_mark=int(netaddr.IPAddress(vm_ip)))

        ofproto = self.get_datapath().ofproto

        actions = [
            parser.OFPActionSetField(eth_src=self.external_host_mac),
            parser.OFPActionSetField(eth_dst=vm_mac)
                    ]

        actions += [
            parser.NXActionRegLoad(
                            ofs_nbits=nicira_ext.ofs_nbits(31, 31),
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
            inst=inst,
            table_id=const.INGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)
