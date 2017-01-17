
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

from dragonflow import conf as cfg
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from oslo_log import log


LOG = log.getLogger(__name__)


class Classifier(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(Classifier, self).__init__(*args, **kwargs)
        self.integration_bridge = cfg.CONF.df.integration_bridge

    def add_local_port(self, lport):
        network_id = lport.get_external_value('local_network_id')
        ofport = lport.get_external_value('ofport')
        self._make_ingress_classification_flow(lport,
                                               network_id,
                                               ofport)
        self._make_ingress_dispatch_flow(lport, ofport)

    def _make_ingress_dispatch_flow(self, lport,
                                    ofport):
        port_key = lport.get_unique_key()
        match = self.parser.OFPMatch(reg7=port_key)
        actions = [self.parser.OFPActionOutput(ofport,
                                          self.ofproto.OFPCML_NO_BUFFER)]
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            datapath=self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _make_ingress_classification_flow(self,
                                          lport,
                                          network_id,
                                          ofport):
        match = self.parser.OFPMatch(in_port=ofport)
        actions = [
            self.parser.OFPActionSetField(reg6=lport.get_unique_key()),
            self.parser.OFPActionSetField(metadata=network_id)]
        action_inst = self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = self.parser.OFPInstructionGotoTable(
            const.EGRESS_PORT_SECURITY_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath=self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def remove_local_port(self, lport):
        ofport = lport.get_external_value('ofport')
        self._del_ingress_dispatch_flow(lport)
        self._del_ingress_classification_flow(lport, ofport)

    def _del_ingress_dispatch_flow(self, lport):
        port_key = lport.get_unique_key()
        match = self.parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _del_ingress_classification_flow(self, lport, ofport):
        match = self.parser.OFPMatch(in_port=ofport)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
