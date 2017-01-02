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

from ryu.lib.packet import ether_types
from oslo_log import helpers as log_helpers
from oslo_log import log

from dragonflow._i18n import _LE
from dragonflow.controller.common import constants
from dragonflow.controller import df_base_app
from dragonflow.db.models2 import sfc_models

LOG = log.getLogger(__name__)


class SfcApp(df_base_app.DFlowApp):
    @log_helpers.log_method_call
    def switch_features_handler(self, ev):
        self.initialize()

    @log_helpers.log_method_call
    def initialize(self):
        self.mpls_driver = MplsDriver(self)
        self._pp_ingress_ports = collections.defaultdict(set)
        self._pp_egress_ports = collections.defaultdict(set)

    @log_helpers.log_method_call
    def _get_portchain_driver(self, pc):
        proto = pc.protocol
        if proto == pc.PROTO_MPLS:
            return self.mpls_driver
        else:
            raise RuntimeError(
                _LE('Unsupported portchain proto {0}').format(proto),
            )

    @log_helpers.log_method_call
    @df_base_app.register_event(sfc_models.PortPairGroup, 'updated')
    def sfc_portpairgroup_updated(self, ppg, old_ppg):
        pass

    @log_helpers.log_method_call
    @df_base_app.register_event(sfc_models.PortChain, 'created')
    def sfc_portchain_created(self, pc):
        driver = self._get_portchain_driver(pc)

        for fc in pc.flow_classifiers:
            driver.install_encap_flows(pc, fc)
            driver.install_decap_flows(pc, fc)

        for ppg in pc.port_pair_groups:
            driver.install_dispatch_to_ppg_flows(pc, ppg)

            for pp in ppg.port_pairs:
                self._pp_ingress_ports[pp.ingress_port].add(pp)
                self._pp_egress_ports[pp.egress_port].add(pp)

                lport = self.db_store.get_port(pp.egress_port)
                driver.install_sf_egress_flows(pc, ppg, pp, lport)

    @log_helpers.log_method_call
    @df_base_app.register_event(sfc_models.PortChain, 'deleted')
    def sfc_portchain_deleted(self, pc):
        driver = self._get_portchain_driver(pc)

        for fc in pc.flow_classifiers:
            driver.uninstall_encap_flows(pc, fc)
            driver.uninstall_decap_flows(pc, fc)

        for ppg in pc.port_pair_groups:
            driver.uninstall_dispatch_to_ppg_flows(pc, ppg)

            for pp in ppg.port_pairs:
                lport = self.db_store.get_port(pp.egress_port)
                driver.uninstall_sf_egress_flows(pc, ppg, pp, lport)

    @log_helpers.log_method_call
    @df_base_app.register_event(sfc_models.PortChain, 'updated')
    def sfc_portchain_updated(self, pc, old_pc):
        self.delete_portchain(old_pc)
        self.create_portchain(pc)

    @log_helpers.log_method_call
    def add_local_port(self, lport):
        lport_id = lport.get_id()
        if lport_id in self._pp_ingress_ports:
            # Modify PPG ingress flows
            pass
        if lport_id in self._pp_egress_ports:
            # Add PP egress flows
            pass

    @log_helpers.log_method_call
    def add_remote_port(self, lport):
        lport_id = lport.get_id()
        if lport_id in self._pp_ingress_ports:
            # Modify PPG ingress flows
            pass

    @log_helpers.log_method_call
    def remove_local_port(self, lport):
        lport_id = lport.get_id()
        if lport_id in self._pp_ingress_ports:
            # Modify PPG ingress flows
            pass
        if lport_id in self._pp_egress_ports:
            # Remove PP egress flows
            pass

    @log_helpers.log_method_call
    def remove_remote_port(self, lport):
        lport_id = lport.get_id()
        if lport_id in self._pp_ingress_ports:
            # Modify PPG ingress flows
            pass


class MplsDriver(object):
    _ETH_TYPE_TO_TC = {
        ether_types.ETH_TYPE_IP: 0,
        ether_types.ETH_TYPE_IPV6: 1,
    }

    _TC_TO_ETH_TYPE = {v: k for k, v in _ETH_TYPE_TO_TC.items()}
    _SUPPORTED_ETH_TYPES = frozenset(_ETH_TYPE_TO_TC)

    def __init__(self, app):
        self.app = app

    @classmethod
    def _create_label(cls, chain_idx, fc_idx, ppg_idx):
        return ppg_idx | (fc_idx << 8) | (chain_idx << 11)

    @classmethod
    def _get_ingress_label(cls, pc, fc, ppg):
        fc_idx = pc.flow_classifiers.index(fc)
        ppg_idx = pc.port_pair_groups.index(ppg)
        return cls._create_label(pc.chain_id, fc_idx, ppg_idx)

    @classmethod
    def _get_egress_label(cls, pc, fc, ppg):
        return cls._get_ingress_label(pc, fc, ppg) + 1

    @classmethod
    def _get_encap_label(cls, pc, fc):
        # Can be done faster but this reads better
        return cls._get_ingress_label(pc, fc, pc.port_pair_groups[0])

    @classmethod
    def _get_decap_label(cls, pc, fc):
        # Same here
        return cls._get_egress_label(pc, fc, pc.port_pair_groups[-1])

    @log_helpers.log_method_call
    def install_encap_flows(self, pc, fc):
        for eth_type in self._SUPPORTED_ETH_TYPES:
            self.app.mod_flow(
                table_id=constants.SFC_ENCAP_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    reg6=fc.unique_key,
                    eth_type=eth_type,
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionPushMpls(
                                ether_types.ETH_TYPE_MPLS
                            ),
                            self.app.parser.OFPActionSetField(
                                mpls_label=self._get_encap_label(pc, fc),
                            ),
                            self.app.parser.OFPActionSetField(
                                mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                            ),
                        ],
                    ),
                    self.app.parser.OFPInstructionGotoTable(
                        constants.SFC_MPLS_DISPATCH_TABLE
                    ),
                ],
            )

    @log_helpers.log_method_call
    def uninstall_encap_flows(self, pc, fc):
        for eth_type in self._SUPPORTED_ETH_TYPES:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=constants.SFC_ENCAP_TABLE,
                match=self.app.parser.OFPMatch(
                    reg6=fc.unique_key,
                    eth_type=eth_type,
                ),
            )

    @log_helpers.log_method_call
    def install_decap_flows(self, pc, fc):
        for eth_type in self._SUPPORTED_ETH_TYPES:
            self.app.mod_flow(
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_decap_label(pc, fc),
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionPopMpls(eth_type),
                            self.app.parser.OFPActionSetField(
                                reg6=fc.unique_key,
                            ),
                        ],
                    ),
                    self.app.parser.OFPInstructionGotoTable(
                        constants.SFC_END_OF_CHAIN_TABLE,
                    ),
                ],
            )

    @log_helpers.log_method_call
    def uninstall_decap_flows(self, pc, fc):
        self.app.mod_flow(
            command=self.app.ofproto.OFPFC_DELETE,
            table_id=constants.SFC_MPLS_DISPATCH_TABLE,
            match=self.app.parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_MPLS,
                mpls_label=self._get_decap_label(pc, fc),
            ),
        )

    @log_helpers.log_method_call
    def install_dispatch_to_ppg_flows(self, pc, ppg):
        for fc in pc.flow_classifiers:
            # FIXME output to relevant port
            # FIXME group bucket
            pp = ppg.port_pairs[0]
            lport = self.app.db_store.get_port(pp.ingress_port)

            self.app.mod_flow(
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(pc, fc, ppg),
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionOutput(
                                lport.get_external_value('ofport'), 0),
                        ],
                    ),
                ],
            )

    @log_helpers.log_method_call
    def uninstall_dispatch_to_ppg_flows(self, pc, ppg):
        for fc in pc.flow_classifiers:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(pc, fc, ppg),
                ),
            )

    @log_helpers.log_method_call
    def install_sf_egress_flows(self, pc, ppg, pp, lport):
        for fc in pc.flow_classifiers:
            self.app.mod_flow(
                table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    in_port=lport.get_external_value('ofport'),
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(pc, fc, ppg),
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionSetField(
                                mpls_label=self._get_ingress_label(pc, fc,
                                                                   ppg),
                            ),
                        ],
                    ),
                    self.app.parser.OFPInstructionGotoTable(
                        constants.SFC_MPLS_DISPATCH_TABLE,
                    ),
                ],
            )

    @log_helpers.log_method_call
    def uninstall_sf_egress_flows(self, pc, ppg, pp, lport):
        for fc in pc.flow_classifiers:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=constants.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
                match=self.app.parser.OFPMatch(
                    in_port=lport.get_external_value('ofport'),
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(pc, fc, ppg),
                ),
            )
