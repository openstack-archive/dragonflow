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
import itertools

from ryu.lib.packet import ether_types
from oslo_log import helpers as log_helpers
from oslo_log import log

from dragonflow._i18n import _LE
from dragonflow.controller.common import constants
from dragonflow.controller import df_base_app
from dragonflow.db import db_store2
from dragonflow.db.models import sfc_models

LOG = log.getLogger(__name__)


class SfcApp(df_base_app.DFlowApp):
    @log_helpers.log_method_call
    def switch_features_handler(self, ev):
        self.initialize()

    @log_helpers.log_method_call
    def initialize(self):
        self.mpls_driver = MplsDriver(self)
        self.db_store2 = db_store2.get_instance()
        self._local_ports = set()

    def _get_portpair_by_egress_port(self, egress_port):
        return self.db_store2.get_one(
            sfc_models.PortPair(
                egress_port=egress_port,
            ),
            index=sfc_models.PortPair.get_indexes()['egress'],
        )

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

    def _fc_is_local(self, fc):
        lport_id = fc.source_port_id or fc.dest_port_id
        return lport_id in self._local_ports

    def _add_flow_classifier(self, pc, fc):
        driver = self._get_portchain_driver(pc)
        if self._fc_is_local(fc):
            driver.install_encap_flows(pc, fc)
        driver.install_decap_flows(pc, fc)

    def _add_port_pair_group(self, pc, ppg):
        driver = self._get_portchain_driver(pc)
        driver.install_dispatch_to_ppg_flows(pc, ppg)

        for pp in ppg.port_pairs:
            if pp.egress_port in self._local_ports:
                lport = self.db_store.get_port(pp.egress_port)
                driver.install_sf_egress_flows(pc, ppg, pp, lport)

    @log_helpers.log_method_call
    @df_base_app.register_event(sfc_models.PortChain, 'created')
    def sfc_portchain_created(self, pc):
        for fc in pc.flow_classifiers:
            self._add_flow_classifier(pc, fc)
        for ppg in pc.port_pair_groups:
            self._add_port_pair_group(pc, ppg)

    def _remove_flow_classifier(self, pc, fc):
        driver = self._get_portchain_driver(pc)
        if self._fc_is_local(fc):
            driver.uninstall_encap_flows(pc, fc)
        driver.uninstall_decap_flows(pc, fc)

    def _remove_port_pair_group(self, pc, ppg):
        driver = self._get_portchain_driver(pc)
        driver.uninstall_dispatch_to_ppg_flows(pc, ppg)

        for pp in ppg.port_pairs:
            if pp.egress_port in self._local_ports:
                lport = self.db_store.get_port(pp.egress_port)
                driver.uninstall_sf_egress_flows(pc, ppg, pp, lport)

    @log_helpers.log_method_call
    @df_base_app.register_event(sfc_models.PortChain, 'deleted')
    def sfc_portchain_deleted(self, pc):
        for fc in pc.flow_classifiers:
            self._remove_flow_classifier(pc, fc)

        for ppg in pc.port_pair_groups:
            self._remove_port_pair_group(pc, ppg)

    @log_helpers.log_method_call
    @df_base_app.register_event(sfc_models.PortChain, 'updated')
    def sfc_portchain_updated(self, pc, old_pc):
        old_fc_ids = set(fc.id for fc in old_pc.flow_classifiers)
        new_fc_ids = set(fc.id for fc in pc.flow_classifiers)
        added_fc_ids = new_fc_ids - old_fc_ids
        removed_fc_ids = old_fc_ids - new_fc_ids

        added_fcs = [
            fc for fc in pc.flow_classifiers if fc.id in added_fc_ids
        ]
        for fc in added_fcs:
            self._add_flow_classifier(pc, fc)

        removed_fcs = [
            fc for fc in old_pc.flow_classifiers if fc in removed_fc_ids
        ]
        for fc in removed_fcs:
            self._remove_flow_classifier(pc, fc)

        # Port pairs groups are more complex since labels depend on index :(
        for old_ppg, new_ppg in itertools.izip_longest(
            old_pc.port_pair_groups,
            pc.port_pair_groups,
        ):
            if new_ppg is not None and old_ppg is None:
                # New chain is longer
                self._add_port_pair_group(old_pc, old_ppg)
            elif old_ppg is not None and new_ppg is None:
                # New chain is shorter
                self._remove_port_pair_group(pc, new_ppg)
            elif new_ppg.id != old_ppg.id:
                # At most one is None so here we have both present
                self._remove_port_pair_group(old_pc, old_ppg)
                self._add_port_pair_group(pc, new_ppg)

    def _get_relevant_fcs(self, lport_id):
        res = []
        res.extend(
            self.db_store2.get_all(
                sfc_models.FlowClassifier(
                    source_port_id=lport_id,
                ),
            ),
            index=sfc_models.get_indexes()['source_port_id'],
        )
        res.extend(
            self.db_store2.get_all(
                sfc_models.FlowClassifier(
                    dest_port_id=lport_id,
                ),
            ),
            index=sfc_models.get_indexes()['dest_port_id'],
        )
        return res

    def _get_relevant_pps(self, lport_id):
        return self.db_store2.get_all(
            sfc_models.PortPair(
                egress_port=lport_id,
            ),
            index=sfc_models.PortPair.get_index()['egress'],
        )

    def _pc_by_fc(self, fc):
        return self.db_store2.get_one(
            sfc_models.PortChain(flow_classifiers=[fc]),
            index=sfc_models.PortChain.get_indexes()['flow_classifiers'],
        )

    def _pc_ppg_by_pp(self, pp):
        ppg = self.db_store2.get_one(
            sfc_models.PortPairGroup(
                port_pairs=[pp],
            ),
            index=sfc_models.PortPairGroup.get_indexes()['port_pairs'],
        )
        if ppg is None:
            return None, None

        pc = self.db_store2.get_one(
            sfc_models.PortChain(
                port_pair_groups=[ppg],
            ),
            index=sfc_models.PortChain.get_indexes()['port_pair_groups'],
        )
        return pc, ppg

    @log_helpers.log_method_call
    def add_local_port(self, lport):
        self._local_ports.add(lport.id)

        # install new encap flows
        for fc in self._get_relevant_fcs(lport.id):
            pc = self._pc_by_fc(fc)
            if pc is not None:
                self._add_flow_classifier(pc, fc)

        # install new SF egress flows
        for pp in self._get_relevant_pps(lport.id):
            ppg, pc = self._ppg_pc_by_pp(pp)
            if pc is not None:
                continue

            driver = self._get_portchain_driver(pc)
            driver.install_sf_egress_flows(pc, ppg, pp, lport)

    @log_helpers.log_method_call
    def add_remote_port(self, lport):
        pass

    @log_helpers.log_method_call
    def remove_local_port(self, lport):
        self._local_ports.remove(lport.id)

        for fc in self._get_relevant_fcs(lport.id):
            pc = self._pc_by_fc(fc)
            if pc is not None:
                self._remove_flow_classifier(pc, fc)

        for pp in self._get_relevant_pps(lport.id):
            ppg, pc = self._ppg_pc_by_pp(pp)
            if pc is None:
                continue

            driver = self._get_portchain_driver(pc)
            driver.uninstall_sf_egress_flows(pc, ppg, pp, lport)

    @log_helpers.log_method_call
    def remove_remote_port(self, lport):
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
    def reinstall_dispatch_to_ppg_flows(self, pc, ppg):
        self.uninstall_dispatch_to_ppg_flows(pc, ppg)
        self.install_dispatch_to_ppg_flows(pc, ppg)

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
