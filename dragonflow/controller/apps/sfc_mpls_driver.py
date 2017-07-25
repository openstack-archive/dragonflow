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
from ryu.lib.packet import ether_types

from dragonflow.controller.apps import sfc_driver_base
from dragonflow.controller.common import constants
from dragonflow.db.models import sfc

LOG = log.getLogger(__name__)


def _get_index_by_id(lst, obj):
    return next(i for i, o in enumerate(lst) if o.id == obj.id)


def _create_group_id(label, extra):
    # FIXME add global way to share group IDs
    return (label << 8) | extra


def _get_dispatch_to_all_group_id(label):
    return _create_group_id(label, 1)


def _get_dispatch_locally_group_id(label):
    return _create_group_id(label, 2)


class _SimpleMplsLabelAllocator(object):
    @classmethod
    def _create_label(cls, chain_idx, fc_idx, ppg_idx):
        return ppg_idx | (fc_idx << 8) | (chain_idx << 11)

    @classmethod
    def _get_ingress_label(cls, port_chain, flow_classifier, port_pair_group):
        fc_idx = _get_index_by_id(
            port_chain.flow_classifiers,
            flow_classifier,
        )

        ppg_idx = _get_index_by_id(
            port_chain.port_pair_groups,
            port_pair_group,
        )

        return cls._create_label(port_chain.chain_id, fc_idx, ppg_idx)

    @classmethod
    def _get_egress_label(cls, port_chain, flow_classifier, port_pair_group):
        label = cls._get_ingress_label(
            port_chain,
            flow_classifier,
            port_pair_group,
        )

        return label + 1

    @classmethod
    def _get_encap_label(cls, port_chain, flow_classifier):
        # Can be done faster but this reads better
        return cls._get_ingress_label(
            port_chain,
            flow_classifier,
            port_chain.port_pair_groups[0],
        )

    @classmethod
    def _get_decap_label(cls, port_chain, flow_classifier):
        # Can be done faster but this reads better
        return cls._get_egress_label(
            port_chain,
            flow_classifier,
            port_chain.port_pair_groups[-1],
        )


class MplsDriver(_SimpleMplsLabelAllocator, sfc_driver_base.SfcBaseDriver):
    _ETH_TYPE_TO_TC = {
        ether_types.ETH_TYPE_IP: 0,
        ether_types.ETH_TYPE_IPV6: 1,
    }

    def __init__(self, app):
        self.app = app

    def install_encap_flows(self, port_chain, flow_classifier):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                table_id=constants.SFC_ENCAP_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    reg2=flow_classifier.unique_key,
                    eth_type=eth_type,
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionPushMpls(
                                ether_types.ETH_TYPE_MPLS,
                            ),
                            self.app.parser.OFPActionSetField(
                                mpls_label=self._get_encap_label(
                                    port_chain,
                                    flow_classifier,
                                ),
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

    def uninstall_encap_flows(self, port_chain, flow_classifier):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE_STRICT,
                table_id=constants.SFC_ENCAP_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    reg2=flow_classifier.unique_key,
                    eth_type=eth_type,
                ),
            )

    def install_decap_flows(self, port_chain, flow_classifier):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_decap_label(
                        port_chain,
                        flow_classifier,
                    ),
                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionPopMpls(eth_type),
                            self.app.parser.OFPActionSetField(
                                reg2=flow_classifier.unique_key,
                            ),
                        ],
                    ),
                    self.app.parser.OFPInstructionGotoTable(
                        constants.SFC_END_OF_CHAIN_TABLE,
                    ),
                ],
            )

    def uninstall_decap_flows(self, port_chain, flow_classifier):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE_STRICT,
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_decap_label(
                        port_chain,
                        flow_classifier
                    ),
                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                ),
            )

    def install_forward_to_dest(self, port_chain, flow_classifier):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_decap_label(
                        port_chain,
                        flow_classifier
                    ),
                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionSetField(
                                reg2=flow_classifier.dest_port.unique_key,
                            ),
                        ],
                    ),
                    self.app.parser.OFPInstructionGotoTable(
                        constants.EGRESS_TABLE,
                    ),
                ],
            )

    def uninstall_forward_to_dest(self, port_chain, flow_classifier):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE_STRICT,
                priority=constants.PRIORITY_HIGH,
                table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_decap_label(
                        port_chain,
                        flow_classifier,
                    ),
                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                ),
            )

    def _port_pair_to_bucket(self, port_pair):
        if (
            port_pair.correlation_mechanism == sfc.CORR_MPLS or
            not port_pair.ingress_port.is_local
        ):
            next_table = constants.EGRESS_TABLE
        else:
            next_table = constants.SFC_MPLS_PP_DECAP_TABLE

        actions = [
            self.app.parser.OFPActionSetField(
                reg7=port_pair.ingress_port.unique_key,
            ),
            self.app.parser.NXActionResubmitTable(table_id=next_table),
        ]
        return self.app.parser.OFPBucket(actions=actions, weight=1)

    def _install_port_pair_decap_flows(self, label):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                table_id=constants.SFC_MPLS_PP_DECAP_TABLE,
                priority=constants.PRIORITY_HIGH,
                match=self.app.parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=label,
                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                ),
                actions=[
                    self.app.parser.OFPActionPopMpls(eth_type),
                    self.app.parser.NXActionResubmitTable(
                        table_id=constants.EGRESS_TABLE,
                    ),
                ],
            )

    def _uninstall_port_pair_decap_flows(self, label):
        self.app.mod_flow(
            command=self.app.ofproto.OFPFC_DELETE_STRICT,
            table_id=constants.SFC_MPLS_PP_DECAP_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.app.parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_MPLS,
                mpls_label=label,
            ),
        )

    def _install_dispatch_to_all_port_pairs(self, port_pair_group, label):
        all_group_id = _get_dispatch_to_all_group_id(label)

        # Add group: pick random SF from all available
        self.app.add_group(
            group_id=all_group_id,
            group_type=self.app.ofproto.OFPGT_SELECT,
            buckets=[
                self._port_pair_to_bucket(pp)
                for pp in port_pair_group.port_pairs
            ],
            replace=True,
        )

        # Add flow: label => execute above group
        self.app.mod_flow(
            table_id=constants.SFC_MPLS_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.app.parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_MPLS,
                mpls_label=label,
            ),
            actions=[self.app.parser.OFPActionGroup(group_id=all_group_id)],
        )

    def _uninstall_dispatch_to_all_port_pairs(self, port_pair_group, label):
        all_group_id = _get_dispatch_to_all_group_id(label)

        # Remove execute group flow
        self.app.mod_flow(
            command=self.app.ofproto.OFPFC_DELETE_STRICT,
            table_id=constants.SFC_MPLS_DISPATCH_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.app.parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_MPLS,
                mpls_label=label,
            ),
        )

        # Delete group
        self.app.del_group(
            group_id=all_group_id,
            group_type=self.app.ofproto.OFPGT_SELECT,
        )

    def _install_dispatch_to_local_port_pairs(self, port_pair_group, label):
        local_pps = [
            pp for pp in port_pair_group.port_pairs if pp.ingress_port.is_local
        ]

        if not local_pps:
            return

        local_group_id = _get_dispatch_locally_group_id(label)

        # Add group: pick random SF from local only
        self.app.add_group(
            group_id=local_group_id,
            group_type=self.app.ofproto.OFPGT_SELECT,
            buckets=[self._port_pair_to_bucket(pp) for pp in local_pps],
            replace=True,
        )

        # Add flow: label => execute above group
        self.app.mod_flow(
            table_id=constants.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            priority=constants.PRIORITY_VERY_HIGH,
            match=self.app.parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_MPLS,
                mpls_label=label,
            ),
            actions=[self.app.parser.OFPActionGroup(group_id=local_group_id)],
        )

    def _uninstall_dispatch_to_local_port_pairs(self, port_pair_group, label):
        local_pps = [
            pp for pp in port_pair_group.port_pairs if pp.ingress_port.is_local
        ]
        if not local_pps:
            return

        self.app.mod_flow(
            command=self.app.ofproto.OFPFC_DELETE_STRICT,
            table_id=constants.INGRESS_DESTINATION_PORT_LOOKUP_TABLE,
            priority=constants.PRIORITY_VERY_HIGH,
            match=self.app.parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_MPLS,
                mpls_label=label,
            ),
        )

        local_group_id = _get_dispatch_locally_group_id(label)

        self.app.del_group(
            group_id=local_group_id,
            group_type=self.app.ofproto.OFPGT_SELECT,
        )

    def install_port_pair_group_flows(self, port_chain, port_pair_group):
        for flow_classifier in port_chain.flow_classifiers:
            label = self._get_ingress_label(
                port_chain,
                flow_classifier,
                port_pair_group,
            )

            # Flows to remove MPLS shim for non MPLS service functions
            self._install_port_pair_decap_flows(label)
            self._install_dispatch_to_all_port_pairs(port_pair_group, label)
            self._install_dispatch_to_local_port_pairs(port_pair_group, label)

    def uninstall_port_pair_group_flows(self, port_chain, port_pair_group):
        for flow_classifier in port_chain.flow_classifiers:
            label = self._get_ingress_label(
                port_chain,
                flow_classifier,
                port_pair_group,
            )

            self._uninstall_port_pair_decap_flows(label)
            self._uninstall_dispatch_to_all_port_pairs(port_pair_group, label)
            self._uninstall_dispatch_to_local_port_pairs(
                port_pair_group, label)

    def install_port_pair_egress_flows(self, port_chain, port_pair_group,
                                       port_pair):
        if port_pair.correlation_mechanism == sfc.CORR_MPLS:
            self._install_mpls_port_pair_egress_flows(
                port_chain,
                port_pair_group,
                port_pair,
            )
        elif port_pair.correlation_mechanism == sfc.CORR_NONE:
            self._install_none_port_pair_egress_flows(
                port_chain,
                port_pair_group,
                port_pair,
            )
        else:
            LOG.warning('Driver does not support correlation_mechanism %s',
                        port_pair.correlation_mechanism)

    def _install_mpls_port_pair_egress_flows(self, port_chain, port_pair_group,
                                             port_pair):
        for flow_classifier in port_chain.flow_classifiers:
            self.app.mod_flow(
                table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                priority=constants.PRIORITY_VERY_HIGH,
                match=self.app.parser.OFPMatch(
                    reg6=port_pair.egress_port.unique_key,
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(
                        port_chain,
                        flow_classifier,
                        port_pair_group,
                    ),
                ),
                inst=[
                    self.app.parser.OFPInstructionActions(
                        self.app.ofproto.OFPIT_APPLY_ACTIONS,
                        [
                            self.app.parser.OFPActionSetField(
                                mpls_label=self._get_egress_label(
                                    port_chain,
                                    flow_classifier,
                                    port_pair_group
                                ),
                            ),
                        ],
                    ),
                    self.app.parser.OFPInstructionGotoTable(
                        constants.SFC_MPLS_DISPATCH_TABLE,
                    ),
                ],
            )

    def _install_none_port_pair_egress_flows(self, port_chain, port_pair_group,
                                             port_pair):
        for flow_classifier in port_chain.flow_classifiers:
            mpls_label = self._get_egress_label(
                port_chain,
                flow_classifier,
                port_pair_group,
            )

            for eth_type in self._ETH_TYPE_TO_TC:
                self.app.mod_flow(
                    table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                    priority=constants.PRIORITY_VERY_HIGH,
                    match=self.app.parser.OFPMatch(
                        reg6=port_pair.egress_port.unique_key,
                        eth_type=eth_type,
                    ),
                    actions=[
                        self.app.parser.OFPActionPushMpls(
                            ether_types.ETH_TYPE_MPLS,
                        ),
                        self.app.parser.OFPActionSetField(
                            mpls_label=mpls_label,
                        ),
                        self.app.parser.OFPActionSetField(
                            mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                        ),
                        self.app.parser.NXActionResubmitTable(
                            table_id=constants.SFC_MPLS_DISPATCH_TABLE,
                        ),
                    ],
                )

    def uninstall_port_pair_egress_flows(self, port_chain, port_pair_groups,
                                         port_pair):
        if port_pair.correlation_mechanism == sfc.CORR_MPLS:
            self._uninstall_mpls_port_pair_egress_flows(
                port_chain,
                port_pair_groups,
                port_pair,
            )
        elif port_pair.correlation_mechanism == sfc.CORR_NONE:
            self._uninstall_none_port_pair_egress_flows(port_pair)
        else:
            LOG.warning('Driver does not support correlation_mechanism %s',
                        port_pair.correlation_mechanism)

    def _uninstall_mpls_port_pair_egress_flows(self, port_chain,
                                               port_pair_group, port_pair):
        for flow_classifier in port_chain.flow_classifiers:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE_STRICT,
                table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                priority=constants.PRIORITY_VERY_HIGH,
                match=self.app.parser.OFPMatch(
                    reg6=port_pair.egress_port.unique_key,
                    eth_type=ether_types.ETH_TYPE_MPLS,
                    mpls_label=self._get_ingress_label(
                        port_chain,
                        flow_classifier,
                        port_pair_group,
                    ),
                ),
            )

    def _uninstall_none_port_pair_egress_flows(self, port_pair):
        for eth_type in self._ETH_TYPE_TO_TC:
            self.app.mod_flow(
                command=self.app.ofproto.OFPFC_DELETE_STRICT,
                priority=constants.PRIORITY_VERY_HIGH,
                table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                match=self.app.parser.OFPMatch(
                    reg6=port_pair.egress_port.unique_key,
                    eth_type=eth_type,
                ),
            )
