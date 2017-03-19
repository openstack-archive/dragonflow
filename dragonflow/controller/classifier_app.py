# Copyright (c) 2017 OpenStack Foundation.
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

from oslo_log import log

from dragonflow._i18n import _LI
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from dragonflow.db.models import l2


LOG = log.getLogger(__name__)


class ClassifierApp(df_base_app.DFlowApp):

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_CREATED)
    def _add_local_port(self, lport):
        ofport = lport.ofport
        LOG.info(_LI("Add local ovs port %(ovs_port)s, logical port "
                     "%(lport)s for classification"),
                 {'ovs_port': ofport, 'lport': lport})
        self._make_ingress_classification_flow(lport, ofport)
        self._make_ingress_dispatch_flow(lport, ofport)

    def _make_ingress_dispatch_flow(self, lport,
                                    ofport):
        port_key = lport.unique_key
        match = self.parser.OFPMatch(reg7=port_key)
        LOG.debug("match reg7=%(reg7)s for ingress dispatch of %(lport)s",
                  {'reg7': port_key, 'lport': lport})
        actions = [self.parser.OFPActionOutput(ofport,
                                               self.ofproto.OFPCML_NO_BUFFER)]
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _make_ingress_classification_flow(self, lport, ofport):
        match = self.parser.OFPMatch(in_port=ofport)
        network_id = lport.local_network_id
        LOG.debug("match in_port=%(in_port)s for ingress classification "
                  "of %(lport)s in network %(network)s",
                  {'in_port': ofport, 'lport': lport, 'network': network_id})
        actions = [
            self.parser.OFPActionSetField(reg6=lport.unique_key),
            self.parser.OFPActionSetField(metadata=network_id)]
        action_inst = self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = self.parser.OFPInstructionGotoTable(
            const.EGRESS_PORT_SECURITY_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_DELETED)
    def _remove_local_port(self, lport):
        self._del_ingress_dispatch_flow(lport)
        self._del_ingress_classification_flow(lport)

    def _del_ingress_dispatch_flow(self, lport):
        port_key = lport.unique_key
        LOG.debug("delete ingress dispatch flow for port_key=%(port_key)s",
                  {'port_key': port_key})
        match = self.parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            table_id=const.INGRESS_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _del_ingress_classification_flow(self, lport):
        ofport = lport.ofport
        LOG.debug("delete in_port=%(in_port)s ingress classification",
                  {'in_port': ofport})
        match = self.parser.OFPMatch(in_port=ofport)
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
