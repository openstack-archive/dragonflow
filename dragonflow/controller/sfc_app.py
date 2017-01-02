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

from dragonflow._i18n import _LE
from dragonflow.controller import df_base_app
from dragonflow.controller import sfc_mpls_driver
from dragonflow.db.models import constants as model_const
from dragonflow.db.models import sfc

LOG = log.getLogger(__name__)


class SfcApp(df_base_app.DFlowApp):
    @log_helpers.log_method_call
    def switch_features_handler(self, ev):
        self.initialize()

    @log_helpers.log_method_call
    def initialize(self):
        self.mpls_driver = sfc_mpls_driver.MplsDriver(self)
        self._local_ports = set()

    def _get_portpair_by_egress_port(self, egress_port):
        return self.db_store2.get_one(
            sfc.PortPair(
                egress_port=egress_port,
            ),
            index=sfc.PortPair.get_indexes()['egress'],
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
        sfc.PortPairGroup,
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
        sfc.PortChain,
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
        sfc.PortChain,
        model_const.EVENT_DELETED,
    )
    def sfc_portchain_deleted(self, pc):
        for fc in pc.flow_classifiers:
            self._remove_flow_classifier(pc, fc)

        for ppg in pc.port_pair_groups:
            self._remove_port_pair_group(pc, ppg)

    @log_helpers.log_method_call
    @df_base_app.register_event(
        sfc.PortChain,
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
                sfc.FlowClassifier(
                    source_port_id=lport_id,
                ),
                index=(
                    sfc.FlowClassifier.get_indexes()['source_port_id']
                ),
            ),
        )
        res.extend(
            self.db_store2.get_all(
                sfc.FlowClassifier(
                    dest_port_id=lport_id,
                ),
                index=sfc.FlowClassifier.get_indexes()['dest_port_id'],
            ),
        )
        return res

    def _get_relevant_pps(self, lport_id):
        return self.db_store2.get_all(
            sfc.PortPair(
                egress_port=lport_id,
            ),
            index=sfc.PortPair.get_indexes()['egress'],
        )

    def _pc_by_fc(self, fc):
        return self.db_store2.get_one(
            sfc.PortChain(flow_classifiers=[fc]),
            index=sfc.PortChain.get_indexes()['flow_classifiers'],
        )

    def _pc_by_ppg(self, ppg):
        return self.db_store2.get_one(
            sfc.PortChain(
                port_pair_groups=[ppg],
            ),
            index=sfc.PortChain.get_indexes()['port_pair_groups'],
        )

    def _pc_ppg_by_pp(self, pp):
        ppg = self.db_store2.get_one(
            sfc.PortPairGroup(
                port_pairs=[pp],
            ),
            index=sfc.PortPairGroup.get_indexes()['port_pairs'],
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
