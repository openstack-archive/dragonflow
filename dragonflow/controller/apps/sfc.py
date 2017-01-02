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
from dragonflow.controller.apps import sfc_mpls_driver
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_const
from dragonflow.db.models import l2
from dragonflow.db.models import sfc

LOG = log.getLogger(__name__)


class SfcApp(df_base_app.DFlowApp):
    def switch_features_handler(self, ev):
        self.initialize()

    def initialize(self):
        self.mpls_driver = sfc_mpls_driver.MplsDriver(self)

    def _get_port_chain_driver(self, port_chain):
        proto = port_chain.protocol
        if proto == sfc.PROTO_MPLS:
            return self.mpls_driver
        else:
            raise RuntimeError(
                _('Unsupported portchain proto {0}').format(proto),
            )

    @df_base_app.register_event(sfc.PortPairGroup, model_const.EVENT_UPDATED)
    def _port_pair_group_updated(self, port_pair_group, old_port_pair_group):

        port_chain = self._port_chain_by_port_pair_group(
            port_pair_group,
        )

        if port_chain is None:
            return

        driver = self._get_port_chain_driver(port_chain)
        # FIXME (dimak) maybe use modify
        driver.uninstall_port_pair_group_flows(
            port_chain,
            old_port_pair_group,
        )
        driver.install_port_pair_group_flows(
            port_chain,
            port_pair_group,
        )

        for old_pp, new_pp in itertools.izip_longest(
            port_pair_group.port_pairs,
            old_port_pair_group.port_pairs,
        ):
            if old_pp is not None and new_pp is None:
                self._uninstall_port_pair_egress(
                    port_chain,
                    old_port_pair_group,
                    old_pp,
                )
            elif old_pp is None and new_pp is not None:
                self._install_port_pair_egress(
                    port_chain,
                    port_pair_group,
                    new_pp,
                )
            elif old_pp.id == new_pp.id:
                continue
            else:
                self._install_port_pair_egress(
                    port_chain,
                    port_pair_group,
                    new_pp,
                )
                self._uninstall_port_pair_egress(
                    port_chain,
                    old_port_pair_group,
                    old_pp,
                )

    def _add_port_pair_group(self, port_chain, port_pair_group):
        driver = self._get_port_chain_driver(port_chain)
        driver.install_port_pair_group_flows(
            port_chain,
            port_pair_group,
        )

        for pp in port_pair_group.port_pairs:
            self._install_port_pair_egress(
                port_chain,
                port_pair_group,
                pp,
            )

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_CREATED)
    def _port_chain_created(self, port_chain):
        driver = self._get_port_chain_driver(port_chain)
        for fc in port_chain.flow_classifiers:
            driver.install_flow_classifier(port_chain, fc)

        for ppg in port_chain.port_pair_groups:
            self._add_port_pair_group(port_chain, ppg)

    def _remove_port_pair_group(self, port_chain, port_pair_group):
        driver = self._get_port_chain_driver(port_chain)
        driver.uninstall_port_pair_group_flows(
            port_chain,
            port_pair_group,
        )

        for pp in port_pair_group.port_pairs:
            self._uninstall_port_pair_egress(
                port_chain,
                port_pair_group,
                pp,
            )

    def _install_port_pair_egress(self, port_chain, port_pair_group,
                                  port_pair):
        if port_pair.egress_port.is_local:
            driver = self._get_port_chain_driver(port_chain)
            driver.install_port_pair_egress_flows(
                port_chain,
                port_pair_group,
                port_pair,
            )

    def _uninstall_port_pair_egress(self, port_chain, port_pair_group,
                                    port_pair):
        if port_pair.egress_port.is_local:
            driver = self._get_port_chain_driver(port_chain)
            driver.uninstall_port_pair_egress_flows(
                port_chain,
                port_pair_group,
                port_pair,
            )

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_DELETED)
    def _port_chain_deleted(self, port_chain):
        driver = self._get_port_chain_driver(port_chain)

        for fc in port_chain.flow_classifiers:
            driver.uninstall_flow_classifier(port_chain, fc)

        for ppg in port_chain.port_pair_groups:
            self._remove_port_pair_group(port_chain, ppg)

    @df_base_app.register_event(sfc.PortChain, model_const.EVENT_UPDATED)
    def _port_chain_updated(self, port_chain, old_port_chain):
        driver = self._get_port_chain_driver(port_chain)

        old_fc_ids = set(fc.id for fc in old_port_chain.flow_classifiers)
        new_fc_ids = set(fc.id for fc in port_chain.flow_classifiers)

        added_fc_ids = new_fc_ids - old_fc_ids
        removed_fc_ids = old_fc_ids - new_fc_ids

        removed_fcs = (
            fc for fc in old_port_chain.flow_classifiers
            if fc in removed_fc_ids
        )
        for fc in removed_fcs:
            driver.uninstall_flow_classifier(port_chain, fc)

        added_fcs = (
            fc for fc in port_chain.flow_classifiers if fc.id in added_fc_ids
        )
        for fc in added_fcs:
            driver.install_flow_classifier(port_chain, fc)

        # Port pairs groups are more complex since labels depend on index :(
        for old_ppg, new_ppg in itertools.izip_longest(
            old_port_chain.port_pair_groups,
            port_chain.port_pair_groups,
        ):
            if new_ppg is not None and old_ppg is None:
                # New chain is longer
                self._add_port_pair_group(old_port_chain, old_ppg)
            elif old_ppg is not None and new_ppg is None:
                # New chain is shorter
                self._remove_port_pair_group(port_chain, new_ppg)
            elif new_ppg.id != old_ppg.id:
                # At most one is None so here we have both present
                self._remove_port_pair_group(old_port_chain, old_ppg)
                self._add_port_pair_group(port_chain, new_ppg)

    def _flow_classifiers_by_lport(self, lport):
        return itertools.chain(
            self.db_store.get_all(
                sfc.FlowClassifier(source_port=lport),
                index=sfc.FlowClassifier.get_index('source_port'),
            ),
            self.db_store.get_all(
                sfc.FlowClassifier(dest_port=lport),
                index=sfc.FlowClassifier.get_index('dest_port'),
            ),
        )

    def _port_pairs_by_lport(self, lport):
        return self.db_store.get_all(
            sfc.PortPair(egress_port=lport),
            index=sfc.PortPair.get_index('egress'),
        )

    def _port_chain_by_flow_classifier(self, flow_classifier):
        return self.db_store.get_one(
            sfc.PortChain(flow_classifiers=[flow_classifier]),
            index=sfc.PortChain.get_index('flow_classifiers'),
        )

    def _port_chain_by_port_pair_group(self, port_pair_group):
        return self.db_store.get_one(
            sfc.PortChain(
                port_pair_groups=[port_pair_group],
            ),
            index=sfc.PortChain.get_index('port_pair_groups'),
        )

    def _port_chain_with_port_pair_group_by_port_pair(self, port_pair):
        port_pair_group = self.db_store.get_one(
            sfc.PortPairGroup(
                port_pairs=[port_pair],
            ),
            index=sfc.PortPairGroup.get_index('port_pairs'),
        )
        if port_pair_group is not None:
            return (
                self._port_chain_by_port_pair_group(port_pair_group),
                port_pair_group,
            )

        return None, None

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    def _local_lport_created(self, lport):
        # install new encap/decap flows
        for fc in self._flow_classifiers_by_lport(lport):
            port_chain = self._port_chain_by_flow_classifier(fc)
            if port_chain is not None:
                driver = self._get_port_chain_driver(port_chain)
                driver.install_flow_classifier(port_chain, fc)

        # install new SF egress flows
        for pp in self._port_pairs_by_lport(lport):
            port_chain, port_pair_group = \
                    self._port_chain_with_port_pair_group_by_port_pair(pp)
            if port_chain is not None:
                driver = self._get_port_chain_driver(port_chain)
                driver.install_port_pair_egress_flows(
                    port_chain,
                    port_pair_group,
                    pp,
                )

                # To refresh the dispatch groups
                driver.uninstall_port_pair_group_flows(
                    port_chain,
                    port_pair_group,
                )
                driver.install_port_pair_group_flows(
                    port_chain,
                    port_pair_group,
                )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _local_lport_deleted(self, lport):
        for fc in self._flow_classifiers_by_lport(lport):
            port_chain = self._port_chain_by_flow_classifier(fc)
            if port_chain is not None:
                driver = self._get_port_chain_driver(port_chain)
                driver.uninstall_flow_classifier(port_chain, fc)

        for pp in self._port_pairs_by_lport(lport):
            port_chain, port_pair_group = \
                    self._port_chain_with_port_pair_group_by_port_pair(pp)
            if port_chain is not None:
                driver = self._get_port_chain_driver(port_chain)
                driver.uninstall_port_pair_egress_flows(
                    port_chain, port_pair_group, pp)

                driver.uninstall_port_pair_group_flows(
                    port_chain,
                    port_pair_group,
                )
                driver.install_port_pair_group_flows(
                    port_chain,
                    port_pair_group,
                )
