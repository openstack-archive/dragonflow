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
import netaddr
from oslo_log import log
from ryu.ofproto import ether
from ryu.ofproto import nicira_ext

from dragonflow._i18n import _LI
from dragonflow.common import constants as df_common_const
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import arp_responder
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app

LOG = log.getLogger(__name__)


class BaseSNATApp(df_base_app.DFlowApp):
    """sNAT application base class provides common services

    Application requirements:
    OVS version >= 2.6 should be part of configuration
        OVS_INSTALL_FROM_GIT=True
        OVS_BRANCH=branch-2.6

    Common services includes:
    - arp flows install/uninstall
    - common connection tracking and goto flows required for sNAT
    - overrides common endpoints entries where sNAT application get called
        - add_local_port()
        - remove_local_port()
    """
    def __init__(self, *args, **kwargs):
        LOG.info(_LI("Loading SNAT application ... "))
        super(BaseSNATApp, self).__init__(*args, **kwargs)
        self.external_network_bridge = (
            cfg.CONF.df_dnat_app.external_network_bridge)
        self.ex_peer_patch_port = (
            cfg.CONF.df_dnat_app.ex_peer_patch_port)
        self.external_bridge_mac = const.EMPTY_MAC
        self.chassis = None
        # next parameter counts number of connected compute ports
        # NOTE: not using LogicalNetworks cache
        #             since a simple counter is required
        self.count = 0

    def switch_features_handler(self, ev):
        self.external_ofport = self.vswitch_api.get_port_ofport(
                self.ex_peer_patch_port)

    def ovs_port_updated(self, ovs_port):
        if ovs_port.get_name() != self.external_network_bridge:
            return

        LOG.debug("Ex. Bridge port update is called ... ")
        mac = ovs_port.get_mac_in_use()
        if mac in (None, const.EMPTY_MAC, self.external_bridge_mac):
            return

        self.external_bridge_mac = mac

        if self.chassis is None:
            return

        self.ovs_port_updated_helper()

    def _install_arp_responder(self, host_ip, host_mac):
        # install host arp responder flow rules
        if netaddr.IPAddress(host_ip).version != 4:
            return
        arp_responder.ArpResponder(
            self,
            None,
            host_ip,
            host_mac,
            const.INGRESS_NAT_TABLE).add()

    def _remove_arp_responder(self, host_ip, host_mac):
        # install host arp responder flow rules
        if netaddr.IPAddress(host_ip).version != 4:
            return
        arp_responder.ArpResponder(
            self,
            None,
            host_ip,
            host_mac,
            const.INGRESS_NAT_TABLE).remove()

    def is_data_port(self, lport):
        return df_utils.is_port_owner_of_type(
            lport.get_device_owner(),
            df_common_const.DATA_DEVICE_OWNER)

    def remove_local_port(self, lport):
        """override remove_local_port method to remove installed flows

        :param lport:  local logical port which is being removed
        """
        LOG.info(_LI("SNAT application: remove local port %(lport)s"),
                 {'lport': lport})

        # verify and update connected compute port amount
        if self.is_data_port(lport):
            self.count -= 1

            # remove SNAT related flows only on last VM port removal
            if (self.count == 0):
                self.remove_strategy_based_flows()

            # remove VM specific flows
            self.remove_lport_based_flows(lport)
        else:
            LOG.info(_LI('SNAT application: not a compute port, skipped'))

    def add_local_port(self, lport):
        """override add_local_port method to install sNAT related flows

        :param lport:  local logical port which is being added
        """
        LOG.info(_LI("SNAT application: add local port %(lport)s"),
                 {'lport': lport})

        # install flows only when compute port is added
        if self.is_data_port(lport):
            self.chassis = lport.get_chassis()
            # install flows only on first port add
            # flows are agnostic of port amount and tenant id
            if(self.count == 0):
                self.install_strategy_based_flows()

            self.install_lport_based_flows(lport)

            # update connected VM amount
            self.count += 1

        else:
            LOG.info(_LI('SNAT application: not a compute port, skipped'))

    def ovs_port_updated_helper(self):
        """update already installed flows that depends on br-ex update

        :returns None
        """
        pass

    def install_strategy_based_flows(self):
        """install strategy based flows required to support given sNAT strategy

        Common part to be used by derived class implementation
        :returns None
        """
        self._install_ingress_goto_rules()
        self._install_snat_ingress_conntrack()
        self._install_egress_goto_rules()

    def install_lport_based_flows(self, lport):
        """install port specific flows required to support given sNAT strategy

        :param added port
        :type dictionary
        :returns None
        """
        pass

    def remove_strategy_based_flows(self):
        """remove strategy based flows required to support given sNAT strategy

        Common part to be used by derived class implementation
        :returns None
        """
        parser = self.parser
        ofproto = self.ofproto

        match = parser.OFPMatch(in_port=self.external_ofport)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_DEFAULT,
            match=match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM_LOW,
            match=match)

    def remove_lport_based_flows(self, lport):
        """remove port specific flows required to support given sNAT strategy

        :param port to remove
        :type dictionary
        :returns None
        """
        pass

    def _install_egress_goto_rules(self):
        parser = self.parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        self.add_flow_go_to_table(
            const.L3_LOOKUP_TABLE,
            const.PRIORITY_MEDIUM_LOW,
            const.EGRESS_NAT_TABLE,
            match=match)

    def _install_ingress_goto_rules(self):
        parser = self.parser
        match = parser.OFPMatch(in_port=self.external_ofport)

        self.add_flow_go_to_table(
            const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            const.PRIORITY_DEFAULT,
            const.INGRESS_NAT_TABLE,
            match=match)

    def _install_snat_egress_conntrack(self, match, ext_host_ip):
        """implements single sNAT pass for multiple tenant deployment

        :param match - OVS match expression passed as a parameter
        :param ext_host_ip - unique ip to translate tenant IPs to it
        :returns None
        ----Translation logic follows next rules:----

        ipv4_src -> reg5  (temporary save internal tenant local IP)
        reg6 -> ipv4_src  (replace content of ipv4_src with host unique value)
        last_bit(1) -> ipv4_src  (turn unique value into legal IP address)
        reg6-> ct_mark (save unique value associated with port into
                                    OS  conn. track table)
        reg5 -> ct_label (save original tenant local IP for return flow)
        """
        parser = self.parser
        ofproto = self.ofproto

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
                        value=1,),
            parser.NXActionCT(
                     alg=0,
                     flags=const.CT_FLAG_COMMIT,
                     recirc_table=const.EGRESS_SNAT_TABLE,
                     zone_ofs_nbits=const.NAT_TRACKING_ZONE,
                     zone_src='',
                     actions=[
                            parser.NXActionNAT(
                                flags=const.CT_FLAG_COMMIT,
                                range_ipv4_min=ext_host_ip,
                                range_ipv4_max=ext_host_ip,
                                    ),
                            parser.NXActionRegMove(
                                dst_field='ct_mark',
                                src_field='reg6',
                                n_bits=32),
                            parser.NXActionRegMove(
                                dst_field='ct_label',
                                src_field='reg5',
                                n_bits=32),
                              ]
                          )
                    ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        inst = [action_inst]

        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_egress_after_conntrack(self, match, ext_host_mac):
        parser = self.parser
        ofproto = self.ofproto

        actions = [
            parser.OFPActionSetField(eth_src=ext_host_mac),
            parser.OFPActionSetField(eth_dst=self.external_bridge_mac)
                ]

        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_EXTERNAL_TABLE)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            inst=inst,
            table_id=const.EGRESS_SNAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_ingress_conntrack(self):
        parser = self.parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        ofproto = self.ofproto
        actions = [
            parser.NXActionCT(
                alg=0,
                flags=0,
                recirc_table=const.INGRESS_SNAT_TABLE,
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
            inst=inst,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _install_snat_ingress_after_conntrack(self,
                                              unique_key,
                                              vm_mac,
                                              external_host_mac):
        """complements reverse sNAT translation from unique IP to tenant IP

        :param unique_key - key to match with
        :param vm_mac - original VM mac address to restore
        :returns None

        ---Translation complement follows next rules:---
        unique_key -> reg7 ( load unique port key into dedicated register)
        ct_label -> ipv4_src (restore original local tenant IP)
        change src/dst mac addresses to push packet further to destination
        """
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ct_mark=int(unique_key))

        actions = [
            parser.OFPActionSetField(eth_src=external_host_mac),
            parser.OFPActionSetField(eth_dst=vm_mac),
            parser.NXActionRegLoad(
                            ofs_nbits=nicira_ext.ofs_nbits(0, 31),
                            dst='reg7',
                            value=unique_key),
            parser.NXActionRegMove(
                            src_field='ct_label',
                            dst_field='ipv4_dst',
                            n_bits=32)
                   ]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.INGRESS_DISPATCH_TABLE)
        inst = [action_inst, goto_inst]

        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_SNAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)
