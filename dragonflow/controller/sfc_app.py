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

from oslo_log import helpers as log_helpers
from oslo_log import log
from ryu.lib.packet import ether_types

from dragonflow._i18n import _LE
from dragonflow.controller.common import constants
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_const
from dragonflow.db.models import sfc_models

LOG = log.getLogger(__name__)


class SfcApp(df_base_app.DFlowApp):
    @log_helpers.log_method_call
    def switch_features_handler(self, ev):
        self.initialize()

    @log_helpers.log_method_call
    def initialize(self):
        self.mpls_driver = MplsDriver(self)
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
    @df_base_app.register_event(
        sfc_models.PortPairGroup,
        model_const.EVENT_UPDATED,
    )
    def sfc_portpairgroup_updated(self, ppg, old_ppg):
        pc = self._pc_by_ppg(ppg)
        if pc is None:
            return

        driver = self._get_portchain_driver(pc)
        # FIXME maybe use modify
        driver.uninstall_dispatch_to_ppg_flows(pc, old_ppg)
        driver.install_dispatch_to_ppg_flows(pc, ppg)

        for old_pp, new_pp in itertools.izip_longest(
            ppg.port_pairs,
            old_ppg.port_pairs,
        ):
            if old_pp is not None and new_pp is None:
                self._uninstall_pp_egress(pc, old_ppg, old_pp)
            elif old_pp is None and new_pp is not None:
                self._install_pp_egress(pc, ppg, new_pp)
            elif old_pp.id == new_pp.id:
                continue
            else:
                self._install_pp_egress(pc, ppg, new_pp)
                self._uninstall_pp_egress(pc, old_ppg, old_pp)

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
            self._install_pp_egress(pc, ppg, pp)

    @log_helpers.log_method_call
    @df_base_app.register_event(
        sfc_models.PortChain,
        model_const.EVENT_CREATED,
    )
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
            self._uninstall_pp_egress(pc, ppg, pp)

    def _install_pp_egress(self, pc, ppg, pp):
        if pp.egress_port in self._local_ports:
            driver = self._get_portchain_driver(pc)
            driver.install_sf_egress_flows(pc, ppg, pp)

    def _uninstall_pp_egress(self, pc, ppg, pp):
        if pp.egress_port in self._local_ports:
            driver = self._get_portchain_driver(pc)
            driver.uninstall_sf_egress_flows(pc, ppg, pp)

    @log_helpers.log_method_call
    @df_base_app.register_event(
        sfc_models.PortChain,
        model_const.EVENT_DELETED,
    )
    def sfc_portchain_deleted(self, pc):
        for fc in pc.flow_classifiers:
            self._remove_flow_classifier(pc, fc)

        for ppg in pc.port_pair_groups:
            self._remove_port_pair_group(pc, ppg)

    @log_helpers.log_method_call
    @df_base_app.register_event(
        sfc_models.PortChain,
        model_const.EVENT_UPDATED,
    )
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
                index=(
                    sfc_models.FlowClassifier.get_indexes()['source_port_id']
                ),
            ),
        )
        res.extend(
            self.db_store2.get_all(
                sfc_models.FlowClassifier(
                    dest_port_id=lport_id,
                ),
                index=sfc_models.FlowClassifier.get_indexes()['dest_port_id'],
            ),
        )
        return res

    def _get_relevant_pps(self, lport_id):
        return self.db_store2.get_all(
            sfc_models.PortPair(
                egress_port=lport_id,
            ),
            index=sfc_models.PortPair.get_indexes()['egress'],
        )

    def _pc_by_fc(self, fc):
        return self.db_store2.get_one(
            sfc_models.PortChain(flow_classifiers=[fc]),
            index=sfc_models.PortChain.get_indexes()['flow_classifiers'],
        )

    def _pc_by_ppg(self, ppg):
        return self.db_store2.get_one(
            sfc_models.PortChain(
                port_pair_groups=[ppg],
            ),
            index=sfc_models.PortChain.get_indexes()['port_pair_groups'],
        )

    def _pc_ppg_by_pp(self, pp):
        ppg = self.db_store2.get_one(
            sfc_models.PortPairGroup(
                port_pairs=[pp],
            ),
            index=sfc_models.PortPairGroup.get_indexes()['port_pairs'],
        )
        if ppg is not None:
            return self._pc_by_ppg(ppg), ppg

        return None, None

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
            pc, ppg = self._pc_ppg_by_pp(pp)
            if pc is not None:
                driver = self._get_portchain_driver(pc)
                driver.install_sf_egress_flows(pc, ppg, pp)

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
            pc, ppg = self._pc_ppg_by_pp(pp)
            if pc is not None:
                driver = self._get_portchain_driver(pc)
                driver.uninstall_sf_egress_flows(pc, ppg, pp)

    @log_helpers.log_method_call
    def remove_remote_port(self, lport):
        pass


def _get_index_by_id(lst, obj):
    return next(i for i, o in enumerate(lst) if o.id == obj.id)


class MplsDriver(object):
    _ETH_TYPE_TO_TC = {
        ether_types.ETH_TYPE_IP: 0,
        ether_types.ETH_TYPE_IPV6: 1,
    }

    def __init__(self, app):
        self.app = app

    @classmethod
    def _create_label(cls, chain_idx, fc_idx, ppg_idx):
        return ppg_idx | (fc_idx << 8) | (chain_idx << 11)

    @classmethod
    def _get_ingress_label(cls, pc, fc, ppg):
        fc_idx = _get_index_by_id(pc.flow_classifiers, fc)
        ppg_idx = _get_index_by_id(pc.port_pair_groups, ppg)
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
        for eth_type in self._ETH_TYPE_TO_TC:
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
        for eth_type in self._ETH_TYPE_TO_TC:
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
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_decap_label(pc, fc),
                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
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

    @classmethod
    def _create_group_id(cls, label, extra):
        # FIXME add global way to share group IDs
        return (label << 8) | extra

    @classmethod
    def _get_dispatch_to_all_group_id(cls, label):
        return cls._create_group_id(label, 1)

    @classmethod
    def _get_dispatch_locally_group_id(cls, label):
        return cls._create_group_id(label, 2)

    @log_helpers.log_method_call
    def uninstall_decap_flows(self, pc, fc):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_decap_label(pc, fc),
                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                ),
            )

    def _pp_to_bucket(self, pp):
        lport = self.app.db_store.get_port(pp.ingress_port)
        actions = [
            self.app.parser.OFPActionSetField(reg7=lport.get_unique_key()),
            self.app.parser.NXActionResubmitTable(
                table_id=constants.EGRESS_TABLE,
            )
        ]
        return self.app.parser.OFPBucket(actions=actions, weight=1)

    @log_helpers.log_method_call
    def install_dispatch_to_ppg_flows(self, pc, ppg):
        for fc in pc.flow_classifiers:
            label = self._get_ingress_label(pc, fc, ppg)
            all_group_id = self._get_dispatch_to_all_group_id(label)

            # Add group: pick random SF from all available
            self.app.add_group(
                group_id=all_group_id,
                group_type=self.app.ofproto.OFPGT_SELECT,
                buckets=[self._pp_to_bucket(pp) for pp in ppg.port_pairs],
            )

            # Add flow: label => execute above group
            self.app.mod_flow(
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=label,
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionGroup(
                                group_id=all_group_id,
                            ),
                        ],
                    ),
                ],
            )

            # FIXME Access _local_ports in a nicer way
            local_pps = [
                pp for pp in ppg.port_pairs
                if pp.ingress_port in self.app._local_ports
            ]

            if not local_pps:
                # No local SFs for this PPG, no need to dispatch locally.
                continue

            local_group_id = self._get_dispatch_locally_group_id(label)
            # Add group: pick random SF from local only
            self.app.add_group(
                group_id=local_group_id,
                group_type=self.app.ofproto.OFPGT_SELECT,
                buckets=[self._pp_to_bucket(pp) for pp in local_pps],
            )

            # Add flow: label => execute above group
            self.app.mod_flow(
                table_id=constants.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=label,
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionGroup(
                                group_id=local_group_id,
                            ),
                        ],
                    ),
                ],
            )

    @log_helpers.log_method_call
    def uninstall_dispatch_to_ppg_flows(self, pc, ppg):
        for fc in pc.flow_classifiers:
            label = self._get_ingress_label(pc, fc, ppg)

            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=label,
                ),
            )

            all_group_id = self._get_dispatch_to_all_group_id(label)
            self.app.del_group(
                group_id=all_group_id,
                group_type=self.app.ofproto.OFPGT_SELECT,
            )

            # FIXME Access _local_ports in a nicer way
            local_pps = [
                pp for pp in ppg.port_pairs
                if pp.ingress_port in self.app._local_ports
            ]
            if not local_pps:
                continue

            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=constants.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=label,
                ),
            )
            local_group_id = self._get_dispatch_locally_group_id(label)
            self.app.del_group(
                group_id=local_group_id,
                group_type=self.app.ofproto.OFPGT_SELECT,
            )

    @log_helpers.log_method_call
    def install_sf_egress_flows(self, pc, ppg, pp):
        lport = self.app.db_store.get_port(pp.egress_port)

        for fc in pc.flow_classifiers:
            self.app.mod_flow(
                table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    reg6=lport.get_unique_key(),
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(pc, fc, ppg),
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionSetField(
                                mpls_label=self._get_egress_label(pc, fc, ppg),
                            ),
                        ],
                    ),
                    self.app.parser.OFPInstructionGotoTable(
                        constants.SFC_MPLS_DISPATCH_TABLE,
                    ),
                ],
            )

    @log_helpers.log_method_call
    def uninstall_sf_egress_flows(self, pc, ppg, pp):
        lport = self.app.db_store.get_port(pp.egress_port)

        for fc in pc.flow_classifiers:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE,
                table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                match=self.app.parser.OFPMatch(
                    reg6=lport.get_unique_key(),
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(pc, fc, ppg),
                ),
            )
