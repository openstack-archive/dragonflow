# Copyright (c) 2015 OpenStack Foundation.
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
import struct

from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp
from ryu.lib import addrconv
from ryu.ofproto import ether
from _ast import Delete
from oslo_log import log
from neutron.agent.common import config
from dragonflow._i18n import _LI, _LW
config.setup_logging()
LOG = log.getLogger("dragonflow.controller.df_local_controller")
CT_STATE_NEW = 0x01
CT_STATE_EST = 0x02
CT_STATE_REL = 0x04
CT_STATE_RPL = 0x08
CT_STATE_INV = 0x10
CT_STATE_TRK = 0x20
METADATA_REG = 0x80000408
CT_ZONE_REG = 0x1d402
CT_FLAG_COMMIT = 1
CT_STATE_MASK = CT_STATE_NEW | CT_STATE_EST  | CT_STATE_INV | CT_STATE_TRK
COOKIE_FULLMASK = 0xffffffffffffffff


class SGApp(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(SGApp, self).__init__(*args, **kwargs)
        # TODO(dingbo) local cache related to specific implementation
        self.secgroup_rule_mappings = {}
        self.next_secgroup_rule_id = 0
        self.secgroup_refcount = {}
        self.remote_secgroup_ref = {}
        self.secgroup_associate_ports = {}

    def switch_features_handler(self, ev):
        if self.get_datapath() is None:
            return
        # add default drop flow
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)

        #pre ct zone
        actions = []
        actions.append(parser.NXActionCT(actions=[], alg=0, flags=0,
            recirc_table=const.EGRESS_CONNTRACK_TABLE, zone_ofs_nbits=15,
            zone_src=METADATA_REG))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.EGRESS_PRE_CONNTRACK_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        actions = []
        actions.append(parser.NXActionCT(actions=[], alg=0, flags=0,
            recirc_table=const.INGRESS_CONNTRACK_TABLE, zone_ofs_nbits=15,
            zone_src=METADATA_REG))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.INGRESS_PRE_CONNTRACK_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

        # est state, pass
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_EST, CT_STATE_MASK))
        goto_inst = parser.OFPInstructionGotoTable(
                    const.SERVICES_CLASSIFICATION_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        goto_inst = parser.OFPInstructionGotoTable(
                    const.INGRESS_DISPATCH_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # rel state, pass
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_REL, CT_STATE_MASK))
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        goto_inst = parser.OFPInstructionGotoTable(
                    const.INGRESS_DISPATCH_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # inv state, drop
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_INV, CT_STATE_MASK))
        self.mod_flow(
             self.get_datapath(),
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # new state, goto security group table
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                ct_state=(CT_STATE_TRK | CT_STATE_NEW, CT_STATE_MASK))
        goto_inst = parser.OFPInstructionGotoTable(
                    const.EGRESS_SECURITY_GROUP_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        goto_inst = parser.OFPInstructionGotoTable(
                    const.INGRESS_SECURITY_GROUP_TABLE)
        inst = [goto_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_MEDIUM,
             match=match)

        # defaults to drop packet
        self.mod_flow(
             self.get_datapath(),
             table_id=const.EGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_DEFAULT)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.INGRESS_CONNTRACK_TABLE,
             priority=const.PRIORITY_DEFAULT)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.EGRESS_SECURITY_GROUP_TABLE,
             priority=const.PRIORITY_DEFAULT)

        self.mod_flow(
             self.get_datapath(),
             table_id=const.INGRESS_SECURITY_GROUP_TABLE,
             priority=const.PRIORITY_DEFAULT)
    
    def get_security_rule_dimension(self, secgroup_rule):
        port_range_min = secgroup_rule.port_range_min
        if port_range_min is not None:
            return 3
        else:
            return 2
    def get_security_rule_mapping(self, lrule_id):
        rule_id = self.secgroup_rule_mappings.get(lrule_id)
        LOG.info(_LI("xxxx = %s  %s") %(
                 self.secgroup_rule_mappings,lrule_id))
        if rule_id is not None:
            return rule_id
        else:
            self.next_secgroup_rule_id += 1
            # TODO(dingbo) verify self.next_network_id didnt wrap
            self.secgroup_rule_mappings[lrule_id] = self.next_secgroup_rule_id
            return self.next_secgroup_rule_id
    def remove_local_port(self, lport):

        # TODO(dingbo) remove SG related flow
        if self.get_datapath() is None:
            return
        pass

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        ofport = lport.get_external_value('ofport')
        secgroups = lport.get_security_groups()
        ip = lport.get_ip()
        for secgroup_id in secgroups:
            if self.secgroup_associate_ports.get(secgroup_id) is not None:
                del self.secgroup_associate_ports[secgroup_id]
            secgroup = self.db_store.get_security_group(secgroup_id)
            for rule in secgroup.rules:
                rule_id = self.get_security_rule_mapping(rule.id)
                match = parser.OFPMatch()
                match.set_in_port(ofport)
                msg = parser.OFPFlowMod(
                    datapath=self.get_datapath(),
                    cookie=rule_id,
                    cookie_mask=COOKIE_FULLMASK,
                    table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                    command=ofproto.OFPFC_DELETE,
                    priority=rule_id + 2,
                    out_port=ofproto.OFPP_ANY,
                    out_group=ofproto.OFPG_ANY,
                    match=match)
                self.get_datapath().send_msg(msg)
                
            secrules = self.remote_secgroup_ref.get(secgroup_id)
            if secrules is not None:
                for secrule in secrules:
                    match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                            ipv4_dst=ip)
                    rule_id = self.get_security_rule_mapping(secrule)
                    msg = parser.OFPFlowMod(
                        datapath=self.get_datapath(),
                        cookie=rule_id,
                        cookie_mask=COOKIE_FULLMASK,
                        table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                        command=ofproto.OFPFC_DELETE,
                        priority=rule_id + 2,
                        out_port=ofproto.OFPP_ANY,
                        out_group=ofproto.OFPG_ANY,
                        match=match)
                    self.get_datapath().send_msg(msg)

    def remove_remote_port(self, lport):

        # TODO(dingbo) modify SG related flow
        pass

    def add_local_port(self, lport):

        # TODO(dingbo) add SG related flow
        if self.get_datapath() is None:
            return
        pass

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        ofport = lport.get_external_value('ofport')
        secgroups = lport.get_security_groups()
        ip = lport.get_ip()
        if secgroups is None:
            # install jump flow in pre ct table
            pass
        
        for secgroup_id in secgroups:
            associate_ports = self.secgroup_associate_ports.get(secgroup_id)
            if associate_ports is None:
                self.secgroup_associate_ports[secgroup_id] = set([lport.get_id()])
            else:
                associate_ports.add(lport.get_id())
            secgroup = self.db_store.get_security_group(secgroup_id)
            for rule in secgroup.rules:
                dimensions = self.get_security_rule_dimension(rule)
                rule_id = self.get_security_rule_mapping(rule.id)
                match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
                match.set_in_port(ofport)
                actions = []
                actions.append(parser.NXActionConjunction(clause=0, n_clauses=dimensions, 
                                                          id_=rule_id))
                action_inst = self.get_datapath(). \
                    ofproto_parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS, actions)
    
                inst = [action_inst]
                self.mod_flow(
                    self.get_datapath(),
                    cookie=rule_id,
                    cookie_mask=COOKIE_FULLMASK,
                    inst=inst,
                    table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                    priority=rule_id + 2,
                    match=match)

            secrules = self.remote_secgroup_ref.get(secgroup_id)
            if secrules is not None:
                for secrule in secrules:
                    dimensions = self.get_security_rule_dimension(rule)
                    match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                            ipv4_dst=ip)
                    actions = []
                    rule_id = self.get_security_rule_mapping(secrule)
                    actions.append(parser.NXActionConjunction(clause=dimensions - 1,
                                                            n_clauses=dimensions, 
                                                            id_=rule_id))
                    action_inst = self.get_datapath(). \
                        ofproto_parser.OFPInstructionActions(
                        ofproto.OFPIT_APPLY_ACTIONS, actions)
        
                    inst = [action_inst]
                    self.mod_flow( 
                        self.get_datapath(),
                        cookie=rule_id,
                        cookie_mask=COOKIE_FULLMASK,   
                        inst=inst,
                        table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                        priority=rule_id + 2,
                        match=match)
    def add_remote_port(self, lport):

        # TODO(dingbo) modify SG related flow
        pass

    def add_security_group_rule(self, secgroup, secgroup_rule):

        # TODO(dingbo) modify SG related flow
        if self.get_datapath() is None:
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        remote_group_id = secgroup_rule.remote_group_id
        direction = secgroup_rule.direction
        remote_ip_prefix = secgroup_rule.remote_ip_prefix
        protocol = secgroup_rule.protocol
        port_range_max = secgroup_rule.port_range_max
        port_range_min = secgroup_rule.port_range_min
        ethertype = secgroup_rule.ethertype
        security_group_id = secgroup_rule.security_group_id

        rule_id = self.get_security_rule_mapping(secgroup_rule.id)
        
        if ethertype == 'IPv4':
            dimensions = self.get_security_rule_dimension(secgroup_rule)
            actions = []
            actions.append(parser.NXActionConjunction(clause=1,
                                                      n_clauses=dimensions, 
                                                          id_=rule_id))
            action_inst = self.get_datapath(). \
                ofproto_parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)           
            inst = [action_inst]
            if protocol is not None:
                if protocol == 'icmp':
                    protocol = 1
                elif protocol == 'tcp':
                    if port_range_min is not None:
                        for port in range(int(port_range_min), int(port_range_max)):
                            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                                    ip_proto=6,
                                                    tcp_dst=port)
                            self.mod_flow(
                                self.get_datapath(),
                                cookie=rule_id,
                                cookie_mask=COOKIE_FULLMASK,
                                inst=inst,
                                table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                                priority=rule_id + 2,
                                match=match)
                    else:
                        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                                ip_proto=6)
                        self.mod_flow(
                            self.get_datapath(),
                            cookie=rule_id,
                            cookie_mask=COOKIE_FULLMASK,
                            inst=inst,
                            table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                            priority=rule_id + 2,
                            match=match)
                elif protocol == 'udp':
                    protocol = 17
                else:
                    protocol = int(protocol)
            else:
                match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
                self.mod_flow(
                    self.get_datapath(),
                    cookie=rule_id,
                    cookie_mask=COOKIE_FULLMASK,
                    inst=inst,
                    table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                    priority=rule_id + 2,
                    match=match)

            actions = []
            actions.append(parser.NXActionConjunction(clause=dimensions - 1,
                                                      n_clauses=dimensions, 
                                                          id_=rule_id))
            action_inst = self.get_datapath(). \
                ofproto_parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)            
            inst = [action_inst]
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
            if remote_group_id is not None:
#                 secgroup_id = self.secgroup_mappings.get(security_group_id)
#                 if secgroup_id is None:
#                     self.secgroup_mappings[security_group_id] = self.next_secgroup_id
#                     self.next_secgroup_id += 1

                associate_rules = self.remote_secgroup_ref.get(remote_group_id)
                if associate_rules is None:
                    self.remote_secgroup_ref[remote_group_id] = set([secgroup_rule.id])
                else:
                    associate_rules.add(secgroup_rule.id)
  
                associate_ports = self.secgroup_associate_ports.get(remote_group_id)
                if associate_ports is not None:
                    for lport_id in associate_ports:
                        lport = self.db_store.get_port(lport_id)
                        ip = lport.get_ip()
                        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ipv4_dst=ip)

                        self.mod_flow(
                            self.get_datapath(),
                            cookie=rule_id,
                            cookie_mask=COOKIE_FULLMASK,
                            inst=inst,
                            table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                            priority=rule_id + 2,
                            match=match)
            elif remote_ip_prefix is not None:
                pass
            else:
                self.mod_flow(
                self.get_datapath(),
                cookie=rule_id,
                cookie_mask=COOKIE_FULLMASK,
                inst=inst,
                table_id=const.EGRESS_SECURITY_GROUP_TABLE,
                priority=rule_id + 2,
                match=match)
            
        elif ethertype == 'IPv6':
            pass
        
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, conj_id=rule_id)
        actions = []
        actions.append(parser.NXActionCT(actions= [],  alg= 0,   flags= 1,   recirc_table= const.SERVICES_CLASSIFICATION_TABLE,  zone_ofs_nbits=15,  zone_src=0x1d402))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
                    const.SERVICES_CLASSIFICATION_TABLE)
        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
            cookie=rule_id,
            cookie_mask=COOKIE_FULLMASK,
            inst=inst,
            table_id=const.EGRESS_SECURITY_GROUP_TABLE,
            priority=rule_id + 2,
            match=match)

    def remove_security_group_rule(self, secgroup, secgroup_rule):
        if self.get_datapath() is None:
            return

        rule_id = self.get_security_rule_mapping(secgroup_rule.id)
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        msg = parser.OFPFlowMod(
            datapath=self.get_datapath(),
            cookie=rule_id,
            cookie_mask=COOKIE_FULLMASK,
            table_id=const.EGRESS_SECURITY_GROUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=rule_id + 2,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY)
        self.get_datapath().send_msg(msg)

