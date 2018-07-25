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
from ryu.ofproto import nicira_ext

from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import switch


LOG = log.getLogger(__name__)


class ClassifierApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(ClassifierApp, self).__init__(*args, **kwargs)
        self._ofport_unique_key_map = {}

    def switch_features_handler(self, ev):
        self._ofport_unique_key_map.clear()
        self.add_flow_go_to_table(
            table=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_DEFAULT,
            goto_table_id=self.dfdp.apps['portsec'].entrypoints.default,
        )

    @df_base_app.register_event(
        switch.SwitchPort, model_constants.EVENT_CREATED)
    @df_base_app.register_event(
        switch.SwitchPort, model_constants.EVENT_UPDATED)
    def _switch_port_created(self, switch_port, orig_switch_port=None):
        port_num = switch_port.port_num
        lport_ref = switch_port.lport
        if not lport_ref:
            return  # Not relevant
        if orig_switch_port and orig_switch_port.port_num != port_num:
            self._switch_port_deleted(switch_port)
        if not port_num or port_num == -1:
            return  # Not ready yet, or error
        lport = self.nb_api.get(lport_ref)
        self._ofport_unique_key_map[switch_port.id] = (
            port_num, lport.unique_key)
        LOG.info("Add local ovs port %(switch_port)s, logical port "
                 "%(lport)s for classification",
                 {'switch_port': port_num, 'lport': lport})
        self._make_ingress_classification_flow(lport, port_num)
        self._make_ingress_dispatch_flow(lport, port_num)

    def _make_ingress_dispatch_flow(self, lport,
                                    port_num):
        port_key = lport.unique_key
        match = self.parser.OFPMatch(reg7=port_key)
        LOG.debug("match reg7=%(reg7)s for ingress dispatch of %(lport)s",
                  {'reg7': port_key, 'lport': lport})
        actions = [self.parser.OFPActionOutput(port_num,
                                               self.ofproto.OFPCML_NO_BUFFER)]
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _make_ingress_classification_flow(self, lport, port_num):
        match = self.parser.OFPMatch(in_port=port_num)
        network_id = lport.lswitch.unique_key
        LOG.debug("match in_port=%(in_port)s for ingress classification "
                  "of %(lport)s in network %(network)s",
                  {'in_port': port_num, 'lport': lport, 'network': network_id})
        # Reset in_port to 0 to avoid drop by output command.
        actions = [
            self.parser.OFPActionSetField(reg6=lport.unique_key),
            self.parser.OFPActionSetField(metadata=network_id),
            self.parser.NXActionRegLoad(
                dst='in_port',
                value=0,
                ofs_nbits=nicira_ext.ofs_nbits(0, 31),
            ),
            self.parser.NXActionResubmit(),
        ]
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match,
            actions=actions,
        )

    @df_base_app.register_event(
        switch.SwitchPort, model_constants.EVENT_DELETED)
    def _switch_port_deleted(self, switch_port):
        try:
            port_num, port_key = self._ofport_unique_key_map.pop(
                switch_port.id)
        except KeyError:
            # Port not present in lookup, was either not added, or removed
            # by a previous update. In both cases irrelevant.
            return
        self._del_ingress_dispatch_flow(port_key)
        self._del_ingress_classification_flow(port_num)

    def _del_ingress_dispatch_flow(self, port_key):
        LOG.debug("delete ingress dispatch flow for port_key=%(port_key)s",
                  {'port_key': port_key})
        match = self.parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            table_id=const.INGRESS_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _del_ingress_classification_flow(self, port_num):
        LOG.debug("delete in_port=%(in_port)s ingress classification",
                  {'in_port': port_num})
        match = self.parser.OFPMatch(in_port=port_num)
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
