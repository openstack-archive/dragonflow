
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

from common.logical_networks import LogicalNetworks
from dragonflow._i18n import _LI
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from oslo_log import log


NETWORK_TYPES = ('vlan', 'flat')
VLAN_TYPE = 0
FLAT_TYPE = 1

LOG = log.getLogger(__name__)


class Classifier(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(Classifier, self).__init__(*args, **kwargs)
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.logical_networks = LogicalNetworks()

    def add_local_port(self, lport):
        ofport = lport.get_external_value('ofport')
        network_id = lport.get_external_value('local_network_id')
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

        network_type = lport.get_external_value('network_type')
        print "itamar network type = %s" % network_type
        network_id = lport.get_external_value('local_network_id')

        if network_type not in NETWORK_TYPES:
            print "itamar %s is not supported" % network_type
            return
        if self.logical_networks.get_local_port_count(network_id=network_id,
                network_type=network_type) != 0:
            LOG.info(_LI('classifer for %(network_type)s \
            network id = %(network_id)s, already exist'),
            {'network_id': network_id,
             'network_type': network_type})
        else:
            #only on first port create
            match, actions = self.match_port_by_network_type(lport)
            self.on_first_lport(lport, actions, match)

        self.logical_networks.add_local_port(port_id=lport.get_id(),
                network_id=network_id,
                network_type=network_type)

    def match_port_by_network_type(self, lport):
        network_id = lport.get_external_value('local_network_id')
        segmentation_id = lport.get_external_value('segmentation_id')
        actions = [
            self.parser.OFPActionSetField(metadata=network_id)]
        match = None
        network_type = lport.get_external_value('network_type')
        if network_type == NETWORK_TYPES[VLAN_TYPE]:
            match = self.parser.OFPMatch(vlan_vid=segmentation_id)
            actions.append(self.parser.OFPActionPopVlan())
        elif network_type == NETWORK_TYPES[FLAT_TYPE]:
            match = self.parser.OFPMatch(hvlan_vid=0)

        return match, actions

    def on_first_lport(self, lport, actions, match):
        ofproto = self.get_datapath().ofproto
        action_inst = self.parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = self.parser.OFPInstructionGotoTable(
            const.INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath=self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def remove_local_port(self, lport):
        match = self.parser.OFPMatch(in_port=self.ofport(lport))
        self.mod_flow(
            datapath=self.datapath,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.get_ofproto().OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        #only when there are no ports remove classifier flows
        network_id = lport.get_external_value('network_id')
        network_type = lport.get_external_value('network_type')

        if network_type not in NETWORK_TYPES:
            return
        self.logical_networks.remove_local_port(port_id=lport.get_id(),
                network_id=network_id,
                network_type=network_type)
        if self.logical_networks.get_local_port_count(network_id=network_id,
                network_type=network_type) != 0:
            LOG.info(_LI('non empty network %(network_id)s ,%(network_tyep)s'),
                    {'network_id': network_id,
                     'network_type': network_type})
            return
        #only on first port create
        match, actions = self.match_port_by_network_type(lport)
        self.on_last_lport_down(match)

    def on_last_lport_down(self, match):
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _get_net_type_id(self, network_type):
        return VLAN_TYPE if network_type == 'vlan' else FLAT_TYPE
