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
from dragonflow.db.models import ovs


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
            goto_table_id=const.EGRESS_PORT_SECURITY_TABLE,
        )

    @df_base_app.register_event(ovs.OvsPort, model_constants.EVENT_CREATED)
    @df_base_app.register_event(ovs.OvsPort, model_constants.EVENT_UPDATED)
    def _ovs_port_created(self, ovs_port, orig_ovs_port=None):
        ofport = ovs_port.ofport
        lport_ref = ovs_port.lport
        if not lport_ref:
            return  # Not relevant
        if orig_ovs_port and orig_ovs_port.ofport != ofport:
            self._ovs_port_deleted(ovs_port)
        if not ofport or ofport == -1:
            return  # Not ready yet, or error
        lport = self.nb_api.get(lport_ref)
        self._ofport_unique_key_map[ovs_port.id] = (ofport, lport.unique_key)
        LOG.info("Add local ovs port %(ovs_port)s, logical port "
                 "%(lport)s for classification",
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
        network_id = lport.lswitch.unique_key
        LOG.debug("match in_port=%(in_port)s for ingress classification "
                  "of %(lport)s in network %(network)s",
                  {'in_port': ofport, 'lport': lport, 'network': network_id})
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

    @df_base_app.register_event(ovs.OvsPort, model_constants.EVENT_DELETED)
    def _ovs_port_deleted(self, ovs_port):
        try:
            ofport, port_key = self._ofport_unique_key_map.pop(ovs_port.id)
        except KeyError:
            # OvsPort not present in lookup, was either not added, or removed
            # by a previous update. In both cases irrelevant.
            return
        self._del_ingress_dispatch_flow(port_key)
        self._del_ingress_classification_flow(ofport)

    def _del_ingress_dispatch_flow(self, port_key):
        LOG.debug("delete ingress dispatch flow for port_key=%(port_key)s",
                  {'port_key': port_key})
        match = self.parser.OFPMatch(reg7=port_key)
        self.mod_flow(
            table_id=const.INGRESS_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _del_ingress_classification_flow(self, ofport):
        LOG.debug("delete in_port=%(in_port)s ingress classification",
                  {'in_port': ofport})
        match = self.parser.OFPMatch(in_port=ofport)
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
