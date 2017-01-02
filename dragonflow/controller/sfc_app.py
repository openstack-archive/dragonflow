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

from oslo_log import log

from dragonflow._i18n import _
from dragonflow.controller import df_base_app
from dragonflow.controller import sfc_mpls_driver
from dragonflow.db.models import constants as model_const
from dragonflow.db.models import l2
from dragonflow.db.models import sfc

LOG = log.getLogger(__name__)


class SfcApp(df_base_app.DFlowApp):
    def switch_features_handler(self, ev):
        self.initialize()

    def initialize(self):
        self.mpls_driver = sfc_mpls_driver.MplsDriver(self)

    def _get_portpair_by_egress_port(self, egress_port):
        return self.db_store.get_one(
            sfc.PortPair(egress_port=egress_port),
            index=sfc.PortPair.get_index('egress'),
        )

    def _get_portchain_driver(self, pc):
        proto = pc.protocol
        if proto == sfc.PROTO_MPLS:
            return self.mpls_driver
        else:
            raise RuntimeError(
                _('Unsupported portchain proto {0}').format(proto),
            )

    @df_base_app.register_event(
        sfc.PortPairGroup,
        model_const.EVENT_UPDATED,
    )
    def _sfc_portpairgroup_updated(self, ppg, old_ppg):
        pc = self._pc_by_ppg(ppg)
        if pc is None:
            return

        driver = self._get_portchain_driver(pc)
        # FIXME (dimak) maybe use modify
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

    def _add_flow_classifier(self, pc, fc):
        driver = self._get_portchain_driver(pc)

        if fc.is_classification_local:
            driver.install_encap_flows(pc, fc)

        if fc.is_dispatch_local:
            driver.install_decap_flows(pc, fc)
        else:
            # FIXME (dimak) can be optimized
            driver.install_forward_to_dest(pc, fc)

    def _add_port_pair_group(self, pc, ppg):
        driver = self._get_portchain_driver(pc)
        driver.install_dispatch_to_ppg_flows(pc, ppg)

        for pp in ppg.port_pairs:
            self._install_pp_egress(pc, ppg, pp)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_CREATED)
    def _sfc_portchain_created(self, pc):
        for fc in pc.flow_classifiers:
            self._add_flow_classifier(pc, fc)
        for ppg in pc.port_pair_groups:
            self._add_port_pair_group(pc, ppg)

    def _remove_flow_classifier(self, pc, fc):
        driver = self._get_portchain_driver(pc)
        if fc.is_classification_local:
            driver.uninstall_encap_flows(pc, fc)
        if fc.is_dispatch_local:
            driver.uninstall_decap_flows(pc, fc)
        else:
            driver.uninstall_forward_to_dest(pc, fc)

    def _remove_port_pair_group(self, pc, ppg):
        driver = self._get_portchain_driver(pc)
        driver.uninstall_dispatch_to_ppg_flows(pc, ppg)

        for pp in ppg.port_pairs:
            self._uninstall_pp_egress(pc, ppg, pp)

    def _install_pp_egress(self, pc, ppg, pp):
        if pp.egress_port.is_local:
            driver = self._get_portchain_driver(pc)
            driver.install_sf_egress_flows(pc, ppg, pp)

    def _uninstall_pp_egress(self, pc, ppg, pp):
        if pp.egress_port.is_local:
            driver = self._get_portchain_driver(pc)
            driver.uninstall_sf_egress_flows(pc, ppg, pp)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_DELETED)
    def _sfc_portchain_deleted(self, pc):
        for fc in pc.flow_classifiers:
            self._remove_flow_classifier(pc, fc)

        for ppg in pc.port_pair_groups:
            self._remove_port_pair_group(pc, ppg)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_UPDATED)
    def _sfc_portchain_updated(self, pc, old_pc):
        old_fc_ids = set(fc.id for fc in old_pc.flow_classifiers)
        new_fc_ids = set(fc.id for fc in pc.flow_classifiers)
        added_fc_ids = new_fc_ids - old_fc_ids
        removed_fc_ids = old_fc_ids - new_fc_ids

        removed_fcs = [
            fc for fc in old_pc.flow_classifiers if fc in removed_fc_ids
        ]
        for fc in removed_fcs:
            self._remove_flow_classifier(pc, fc)

        added_fcs = [
            fc for fc in pc.flow_classifiers if fc.id in added_fc_ids
        ]
        for fc in added_fcs:
            self._add_flow_classifier(pc, fc)

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

    def _get_relevant_fcs(self, lport):
        for fc in self.db_store.get_all(
            sfc.FlowClassifier(source_port=lport),
            index=sfc.FlowClassifier.get_index('source_port'),
        ):
            yield fc

        for fc in self.db_store.get_all(
            sfc.FlowClassifier(dest_port=lport),
            index=sfc.FlowClassifier.get_index('dest_port'),
        ):
            yield fc

    def _get_relevant_pps(self, lport):
        return self.db_store.get_all(
            sfc.PortPair(egress_port=lport),
            index=sfc.PortPair.get_index('egress'),
        )

    def _pc_by_fc(self, fc):
        return self.db_store.get_one(
            sfc.PortChain(flow_classifiers=[fc]),
            index=sfc.PortChain.get_index('flow_classifiers'),
        )

    def _pc_by_ppg(self, ppg):
        return self.db_store.get_one(
            sfc.PortChain(
                port_pair_groups=[ppg],
            ),
            index=sfc.PortChain.get_index('port_pair_groups'),
        )

    def _pc_ppg_by_pp(self, pp):
        ppg = self.db_store.get_one(
            sfc.PortPairGroup(
                port_pairs=[pp],
            ),
            index=sfc.PortPairGroup.get_index('port_pairs'),
        )
        if ppg is not None:
            return self._pc_by_ppg(ppg), ppg

        return None, None

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    def _local_lport_created(self, lport):
        # install new encap/decap flows
        for fc in self._get_relevant_fcs(lport):
            pc = self._pc_by_fc(fc)
            if pc is not None:
                driver = self._get_portchain_driver(pc)
                if fc.is_classification_local:
                    driver.install_encap_flows(pc, fc)
                if fc.is_dispatch_local:
                    driver.install_decap_flows(pc, fc)
                else:
                    driver.install_forward_to_dest(pc, fc)

        # install new SF egress flows
        for pp in self._get_relevant_pps(lport):
            pc, ppg = self._pc_ppg_by_pp(pp)
            if pc is not None:
                driver = self._get_portchain_driver(pc)
                driver.install_sf_egress_flows(pc, ppg, pp)

                # To refresh the dispach groups
                driver.uninstall_dispatch_to_ppg_flows(pc, ppg)
                driver.install_dispatch_to_ppg_flows(pc, ppg)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _local_lport_deleted(self, lport):
        for fc in self._get_relevant_fcs(lport):
            pc = self._pc_by_fc(fc)
            if pc is not None:
                driver = self._get_portchain_driver(pc)
                if fc.is_classification_local:
                    driver.uninstall_encap_flows(pc, fc)
                if fc.is_dispatch_local:
                    driver.uninstall_decap_flows(pc, fc)
                else:
                    driver.uninstall_forward_to_dest(pc, fc)

        for pp in self._get_relevant_pps(lport):
            pc, ppg = self._pc_ppg_by_pp(pp)
            if pc is not None:
                driver = self._get_portchain_driver(pc)
                driver.uninstall_sf_egress_flows(pc, ppg, pp)

                driver.uninstall_dispatch_to_ppg_flows(pc, ppg)
                driver.install_dispatch_to_ppg_flows(pc, ppg)
