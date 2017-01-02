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
from oslo_log import helpers as log_helpers
from oslo_log import log
from ryu.lib.packet import ether_types

from dragonflow.controller.common import constants

LOG = log.getLogger(__name__)


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
                                ether_types.ETH_TYPE_MPLS,
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

    def _pp_to_bucket(self, pp):
        lport = self.app.db_store.get_port(pp.ingress_port)
        if pp.correlation_mechanism == 'mpls':
            next_table = constants.EGRESS_TABLE
        else:
            next_table = constants.SFC_MPLS_PP_DECAP_TABLE

        actions = [
            self.app.parser.OFPActionSetField(reg7=lport.get_unique_key()),
            self.app.parser.NXActionResubmitTable(
                table_id=next_table,
            )
        ]
        return self.app.parser.OFPBucket(actions=actions, weight=1)

    def _pp_ingress_to_network_id(self, pp):
        lport = self.app.db_store.get_port(pp.ingress_port)
        lswitch = self.db_store.get_lswitch(lport.get_lswitch_id())
        return lswitch.get_unique_key()

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

            for pp in ppg.port_pairs:
                if pp.correlation_mechanism != 'none':
                    continue

                for eth_type in self._ETH_TYPE_TO_TC:
                    self.app.mod_flow(
                        table_id=constants.SFC_MPLS_PP_DECAP_TABLE,
                        match=self.app.parser.OFPMatch(
                            eth_type=ether_types.ETH_TYPE_MPLS,
                            mpls_label=label,
                            mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                        ),
                        inst=[
                            self.app.parser.OFPInstructionActions(
                                self.app.ofproto.OFPIT_APPLY_ACTIONS,
                                [self.app.parser.OFPActionPopMpls(eth_type)],
                            ),
                            self.app.parser.OFPInstructionGotoTable(
                                constants.EGRESS_TABLE,
                            ),
                        ],
                    )

            # FIXME Access _local_ports in a nicer way
            local_pps = [
                pp for pp in ppg.port_pairs
                if pp.ingress_port in self.app._local_ports
            ]

            if not local_pps:
                return

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

    def install_sf_egress_flows(self, pc, ppg, pp):
        if pp.correlation_mechanism == 'mpls':
            self._install_mpls_sf_egress_flows(pc, ppg, pp)
        elif pp.correlation_mechanism == 'none':
            self._install_none_sf_egress_flows(pc, ppg, pp)

    @log_helpers.log_method_call
    def _install_mpls_sf_egress_flows(self, pc, ppg, pp):
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
    def _install_none_sf_egress_flows(self, pc, ppg, pp):
        lport = self.app.db_store.get_port(pp.egress_port)

        for fc in pc.flow_classifiers:
            mpls_label = self._get_egress_label(pc, fc, ppg)
            for eth_type in self._ETH_TYPE_TO_TC:
                self.app.mod_flow(
                    table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                    priority=constants.PRIORITY_HIGH,
                    match=self.app.parser.OFPMatch(
                        reg6=lport.get_unique_key(),
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
                                    mpls_label=mpls_label,
                                ),
                                self.app.parser.OFPActionSetField(
                                    mpls_tc=self._ETH_TYPE_TO_TC[eth_type],
                                ),
                            ],
                        ),
                        self.app.parser.OFPInstructionGotoTable(
                            constants.SFC_MPLS_DISPATCH_TABLE,
                        ),
                    ],
                )

    def uninstall_sf_egress_flows(self, pc, ppg, pp):
        if pp.correlation_mechanism == 'mpls':
            self._uninstall_mpls_sf_egress_flows(pc, ppg, pp)
        else:
            self._uninstall_none_sf_egress_flows(pc, ppg, pp)

    @log_helpers.log_method_call
    def _uninstall_mpls_sf_egress_flows(self, pc, ppg, pp):
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

    @log_helpers.log_method_call
    def _uninstall_none_sf_egress_flows(self, pc, ppg, pp):
        lport = self.app.db_store.get_port(pp.egress_port)

        for fc in pc.flow_classifiers:
            for eth_type in self._ETH_TYPE_TO_TC:
                self.app.mod_flow(
                    command=self.app.ofproto.OFPFC_DELETE_STRICT,
                    priority=constants.PRIORITY_HIGH,
                    table_id=constants.EGRESS_PORT_SECURITY_TABLE,
                    match=self.app.parser.OFPMatch(
                        reg6=lport.get_unique_key(),
                        eth_type=eth_type,
                    ),
                )
