# Copyright (c) 2016 OpenStack Foundation.
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
from oslo_log import helpers as log_helpers
from oslo_log import log

from dragonflow.controller.common import constants
from dragonflow.controller import df_base_app
from dragonflow.db import models_sfc  # noqa

LOG = log.getLogger(__name__)
OF_IN_PORT = 0xfff8


class FcApp(df_base_app.DFlowApp):
    def switch_features_handler(self, ev):
        self.initialize()

        # Add SFC short-circuit in case SFC app is not loaded
        self.add_flow_go_to_table(constants.SFC_ENCAP_TABLE,
                                  constants.PRIORITY_DEFAULT,
                                  constants.SFC_END_OF_CHAIN_TABLE)

    @log_helpers.log_method_call
    def initialize(self):
        self._local_ports = set()
        self._local_fcs = {}
        self._fc_to_pc = {}
        self._port_to_fc = collections.defaultdict(set)

    @log_helpers.log_method_call
    def add_local_port(self, lport):
        lport_id = lport.get_id()
        self._local_ports.add(lport_id)

        for fc in self._port_to_fc[lport_id]:
            self._install_flow_classifier(fc)

    @log_helpers.log_method_call
    def _install_flow_classifier(self, fc):
        lport = self._get_fc_lport(fc)
        lport_id = lport.get_id()
        if lport_id not in self._local_ports:
            return

        if lport_id == fc.source_port_id:
            self._install_source_flow_classifier(fc, lport)
        elif lport_id == fc.dest_port_id:
            self._install_dest_flow_classifier(fc, lport)

    @log_helpers.log_method_call
    def remove_local_port(self, lport):
        lport_id = lport.get_id()
        self._local_ports.remove(lport_id)

        for fc in self._port_to_fc[lport_id]:
            self._uninstall_flow_classifier(fc)

    @log_helpers.log_method_call
    def _uninstall_flow_classifier(self, fc):
        lport = self._get_fc_lport(fc)
        lport_id = lport.get_id()
        if lport_id not in self._local_ports:
            return

        if lport_id == fc.source_port_id:
            self._uninstall_source_flow_classifier(fc, lport)
        elif lport_id == fc.dest_port_id:
            self._uninstall_dest_flow_classifier(fc, lport)

    @log_helpers.log_method_call
    def _install_source_flow_classifier(self, fc, lport):
        # FIXME assume lport is a vm port for now

        # Classification
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS,
            [self.parser.OFPActionSetField(reg6=fc.unique_key)])
        goto_inst = self.parser.OFPInstructionGotoTable(
            constants.SFC_ENCAP_TABLE)

        self.mod_flow(
            table_id=constants.L2_LOOKUP_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.parser.OFPMatch(
                reg6=lport.get_unique_key(),
            ),
            inst=[
                action_inst,
                goto_inst
            ],
        )

        # End-of-chain
        lswitch = self.db_store.get_lswitch(lport.get_lswitch_id())
        inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS,
            [
                self.parser.OFPActionSetField(reg6=lport.get_unique_key()),
                self.parser.OFPActionSetField(
                    metadata=lswitch.get_unique_key(),
                ),
                self.parser.NXActionResubmitTable(
                    OF_IN_PORT,
                    constants.L2_LOOKUP_CONT_TABLE,
                ),
            ],
        )

        self.mod_flow(
            table_id=constants.SFC_END_OF_CHAIN_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.parser.OFPMatch(reg6=fc.unique_key),
            inst=[inst],
        )

    @log_helpers.log_method_call
    def _uninstall_source_flow_classifier(self, fc, lport):
        # FIXME assume lport is a vm port for now
        self.mod_flow(
            table_id=constants.L2_LOOKUP_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.parser.OFPMatch(reg6=lport.get_unique_key()),
            command=self.ofproto.OFPFC_DELETE_STRICT,
        )
        self._delete_end_of_chain_flow(fc)

    @log_helpers.log_method_call
    def _delete_end_of_chain_flow(self, fc):
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=constants.SFC_END_OF_CHAIN_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.parser.OFPMatch(reg6=fc.unique_key),
        )

    @log_helpers.log_method_call
    def _install_dest_flow_classifier(self, fc, lport):
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS,
            [self.parser.OFPActionSetField(reg6=fc.unique_key)])
        goto_inst = self.parser.OFPInstructionGotoTable(
            constants.SFC_ENCAP_TABLE)

        self.mod_flow(
            table_id=constants.EGRESS_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.parser.OFPMatch(reg7=lport.get_unique_key()),
            inst=[action_inst, goto_inst],
        )

        # End-of-chain
        lswitch = self.db_store.get_lswitch(lport.get_lswitch_id())
        inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS,
            [
                self.parser.OFPActionSetField(reg7=lport.get_unique_key()),
                self.parser.OFPActionSetField(
                    metadata=lswitch.get_unique_key()
                ),
                self.parser.NXActionResubmitTable(
                    OF_IN_PORT,
                    constants.EGRESS_CONT_TABLE,
                ),
            ]
        )

        self.mod_flow(
            table_id=constants.SFC_END_OF_CHAIN_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.parser.OFPMatch(reg6=fc.unique_key),
            inst=[inst],
        )

    @log_helpers.log_method_call
    def _uninstall_dest_flow_classifier(self, fc, lport):
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE_STRICT,
            table_id=constants.EGRESS_TABLE,
            priority=constants.PRIORITY_HIGH,
            match=self.parser.OFPMatch(reg7=lport.get_unique_key()),
        )
        self._delete_end_of_chain_flow(fc)

    @log_helpers.log_method_call
    def _get_fc_lport_id(self, fc):
        return fc.source_port_id or fc.dest_port_id

    @log_helpers.log_method_call
    def _get_fc_lport(self, fc):
        return self.db_store.get_port(self._get_fc_lport_id(fc))

    @log_helpers.log_method_call
    def create_sfc_portchain(self, pc):
        for fc in pc.flowclassifiers:
            self._fc_to_pc[fc.id] = pc
            self._local_fcs[fc.id] = fc
            lport_id = self._get_fc_lport_id(fc)
            self._port_to_fc[lport_id].add(fc.id)

            self._install_flow_classifier(fc)

    @log_helpers.log_method_call
    def delete_sfc_portchain(self, pc):
        for fc in pc.flow_classifiers:
            self._uninstall_flow_classifier(fc)

            self._fc_to_pc.pop(fc.id)
            self._local_fcs.pop(fc.id)
            lport_id = self._get_fc_lport_id(fc)
            self._port_to_fc[lport_id].remove(fc.id)

    @log_helpers.log_method_call
    def update_sfc_portchain(self, pc, old_pc):
        old_fcs = set(fc.id for fc in old_pc.flow_classifiers)
        new_fcs = set(fc.id for fc in pc.flow_classifiers)

        added_fcs = new_fcs - old_fcs
        deleted_fcs = old_fcs - new_fcs

        for fc_id in deleted_fcs:
            fc = self._local_fcs[fc_id]
            self._uninstall_flow_classifier(fc)
            self._local_fcs.pop(fc_id)
            self._fc_to_pc.pop(fc_id)
            lport_id = self._get_fc_lport_id(fc)
            self._port_to_fc[lport_id].remove(fc_id)

        for fc_id in added_fcs:
            fc = self._local_fcs[fc_id]
            self._install_flow_classifier(fc)
            self._local_fcs[fc_id] = fc
            lport_id = self._get_fc_lport_id(fc)
            self._port_to_fc[lport_id].add(fc_id)
