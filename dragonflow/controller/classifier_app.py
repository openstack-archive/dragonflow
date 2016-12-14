
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


import netaddr
from neutron_lib import constants as common_const
from neutron_lib.utils import helpers
from oslo_log import log
from ryu.ofproto import ether
import six

from dragonflow._i18n import _, _LI, _LE
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app

LOG = log.getLogger(__name__)


class Classifier(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(Classifier, self).__init__(*args, **kwargs)
        cfg.CONF.register_opts(CLASSSIFIER_APP_OPTS, group='df_classifier_app')
        self.local_networks = collections.defaultdict(_LocalNetwork)
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.cfg = cfg.CONF.df_classifier_app


    @property
    def parser(self):
        return self.get_datapath().ofproto_parser


    @property
    def ofproto(self):
        return self.get_datapath().ofproto


    @property
    def local_ports(self):
        return self.get_datapath().local_ports


    def create_match(self,**kwargs):
        return self.parser.OFPMatch(**kargs)


    def add_local_port(self, lport):
        match = self.create_match(in_port=lport.get_ofport())
        actions = [
            self.parser.OFPActionSetField(reg6=lport.get_unique_key(),
            self.parser.OFPActionSetField(metadata=lport.get_network_id())
            ]
        action_inst = self.get_parser().OFPInstructionActions(
            self.get_ofproto().OFPIT_APPLY_ACTIONS, actions)

        goto_inst = self.get_parser().OFPInstructionGotoTable(
            const.EGRESS_PORT_SECURITY_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            datapath=self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        if self.local_ports:
            LOG.info(_LI('classifer for network %s ,type already exist',
                self.get_network(),lport.get_network_type()))
            return
        #only on first port create
        network = self.local_networks.get(lport.get_network_id())
        if network and network.local_ports:
            return
        if lport.get_network_type() in ['vlan', 'flat']:
            self.add_port_by_network_type(lport)


    def add_port_by_network_type(self,lport):
        actions = [
            self.parser.OFPActionSetField(lport=self.get_network_id())
            ]
        if lport.get_network_type() == 'vlan'
            match = self.create_match(vlan_vid=get_segmentation_id())
            actions.append(self.parser.OFPActionPopVlan())
        elif lport.get_network_type() == 'flat':
            match = self.create_match(vlan_vid=0)

        self.on_first_lport(lport,actions,match)


    def on_first_lport(self, lport, actions, match):
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
        match = self.create_match(in_port=self.ofport(lport)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.get_ofproto().OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
        #only when there are no ports remove classifier flows
        network = self.local_networks.get(lport.get_network_id())
        if network and network.local_ports:
            return

        if lport.get_network_type() in ['vlan', 'flat']:
            self.del_port_by_network_type(lport)

    def del_port_by_network_type(self,lport):
        LOG.info(_LI("last port down in network"
                     "segmentation_id =%s, "
                     "network_id =%s") %
                 (str(lport.get_segmentation_id(),
                  str(lport.get_network_id())
        if self.get_network_type(lport) == 'flat':
            match = self.create_match(vlan_vid=0)
        elif self.get_network_type(lport) == 'vlan':
            match = self.create_match(vlan_vid=lport.get_segmentation_id())

        self.on_last_lport_down(match)


  def on_last_lport_down(self, match):
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=match)
