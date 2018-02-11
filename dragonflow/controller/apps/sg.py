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

import collections
import copy
import itertools

import netaddr
from neutron_lib import constants as n_const
from oslo_log import log
from ryu.ofproto import ether
from ryu.ofproto import nicira_ext

from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_constants
from dragonflow.db.models import l2
from dragonflow.db.models import secgroups as sg_model
from dragonflow.utils import conntrack


LOG = log.getLogger(__name__)

SG_CT_STATE_MASK = const.CT_STATE_NEW | const.CT_STATE_EST | \
                   const.CT_STATE_REL | const.CT_STATE_INV | const.CT_STATE_TRK
SG_PRIORITY_OFFSET = 2
COOKIE_NAME = 'sg rule'
DIRECTION_INGRESS = 'ingress'
DIRECTION_EGRESS = 'egress'

DEST_FIELD_NAME_BY_PROTOCOL_NUMBER = {
    n_const.PROTO_NUM_TCP: 'tcp_dst',
    n_const.PROTO_NUM_UDP: 'udp_dst',
}

CONNTRACK_PREPARE_TABLE = const.CONNTRACK_PREPARE_TABLE
CONNTRACK_TABLE = const.CONNTRACK_TABLE
CONNTRACK_RESULT_TABLE = const.CONNTRACK_RESULT_TABLE
CONNTRACK_CLEANUP_TABLE = const.CONNTRACK_CLEANUP_TABLE
EGRESS_SECURITY_GROUP_TABLE = const.EGRESS_SECURITY_GROUP_TABLE
INGRESS_SECURITY_GROUP_TABLE = const.INGRESS_SECURITY_GROUP_TABLE
SECURITY_GROUP_EXIT_TABLE = const.INGRESS_DISPATCH_TABLE


class SGApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(SGApp, self).__init__(*args, **kwargs)
        self.secgroup_rule_mappings = {}
        self.next_secgroup_rule_id = 0
        self.remote_secgroup_ref = collections.defaultdict(dict)
        self.secgroup_associate_local_ports = {}
        self.register_local_cookie_bits(COOKIE_NAME, 32)

    def _get_rule_l2_match(self, secgroup_rule):
        if secgroup_rule.ethertype == n_const.IPv4:
            eth_type = ether.ETH_TYPE_IP
        elif secgroup_rule.ethertype == n_const.IPv6:
            eth_type = ether.ETH_TYPE_IPV6
        return {'eth_type': eth_type}

    def _get_rule_l4_matches(self, secgroup_rule):
        """
        Create the match object for the security group rule given in
        secgroup_rule (type SecurityGroupRule).
        """
        protocol = secgroup_rule.protocol
        if not protocol:
            return []

        result_base = {"ip_proto": protocol}
        port_range_min = secgroup_rule.port_range_min
        port_range_max = secgroup_rule.port_range_max
        if protocol == n_const.PROTO_NUM_ICMP:
            if port_range_min:
                if secgroup_rule.ethertype == n_const.IPv4:
                    result_base['icmpv4_type'] = int(port_range_min)
                else:
                    result_base['icmpv6_type'] = int(port_range_min)
            if port_range_max:
                if secgroup_rule.ethertype == n_const.IPv4:
                    result_base['icmpv4_code'] = int(port_range_max)
                else:
                    result_base['icmpv6_code'] = int(port_range_max)
            results = [result_base]
        elif ((not port_range_min and not port_range_max) or
              (int(port_range_min) == const.MIN_PORT and
               int(port_range_max) == const.MAX_PORT)):
            results = [result_base]
        else:
            port_match_list = utils.get_port_match_list_from_port_range(
                port_range_min, port_range_max)
            key = DEST_FIELD_NAME_BY_PROTOCOL_NUMBER[protocol]
            results = []
            for port_match in port_match_list:
                result = result_base.copy()
                result[key] = port_match
                results.append(result)
        return results

    def _get_rule_cookie(self, rule_id):
        local_rule_id = self._get_security_rule_mapping(rule_id)
        return self.get_local_cookie(COOKIE_NAME, local_rule_id)

    @classmethod
    def _get_l3_match_item(cls, ethertype, flow_direction):
        """
        Returns the match_item that should be matched in the flow

        :param ethertype: The ethernet type relevant to the flow {IPv4 | IPv6}
        :param flow_direction: The fidirection of the flow {ingress | egress}
        """
        # XXX Should be constants ('ingress', 'egress')
        match_items = {
            (n_const.IPv4, 'ingress'): 'ipv4_src',
            (n_const.IPv4, 'egress'): 'ipv4_dst',
            (n_const.IPv6, 'ingress'): 'ipv6_src',
            (n_const.IPv6, 'egress'): 'ipv6_dst'
        }
        return match_items.get((ethertype, flow_direction))

    def _install_ipv4_ipv6_rules(self, table_id, match_items, priority=0xff,
                                 command=None, inst=None, actions=None):
        """
        Install identical flows for both IPv4 and IPv6.

        :param table_id:    the table in which the flows will be installed
        :param match_items: a dictionary of fields names and values,
                            to be matched in the flows
        :param priority:    priority level of the flows entries
        :param command:     the flows' command {OFPFC_ADD | OFPFC_MODIFY
                                                | OFPFC_MODIFY_STRICT
                                                | OFPFC_DELETE
                                                | OFPFC_DELETE_STRICT}
        :param inst:        an OFPInstructionActions object, with the
                            requested actions.
        """
        parser = self.parser
        for ip_version in (ether.ETH_TYPE_IP, ether.ETH_TYPE_IPV6):
            self.mod_flow(
                inst=inst,
                actions=actions,
                table_id=table_id,
                priority=priority,
                match=parser.OFPMatch(eth_type=ip_version, **match_items),
                command=command)

    def _install_security_group_permit_flow(self, security_group,
                                            table_id, next_table_id):
        if self._is_sg_not_associated_with_local_port(security_group):
            return

        conj_id, priority = (
            self._get_secgroup_conj_id_and_priority(security_group))

        self.add_flow_go_to_table(table_id,
                                  const.PRIORITY_CT_STATE,
                                  next_table_id,
                                  match=self.parser.OFPMatch(conj_id=conj_id))

    def _install_security_group_flows(self, security_group):
        self._install_security_group_permit_flow(
            security_group,
            EGRESS_SECURITY_GROUP_TABLE,
            INGRESS_SECURITY_GROUP_TABLE)
        self._install_security_group_permit_flow(
            security_group,
            INGRESS_SECURITY_GROUP_TABLE,
            SECURITY_GROUP_EXIT_TABLE)

        for rule in security_group.rules:
            self.add_security_group_rule(security_group, rule)

    def _uninstall_security_group_permit_flow(self, security_group, table_id):
        if self._is_sg_not_associated_with_local_port(security_group):
            return
        ofproto = self.ofproto

        conj_id, priority = (
            self._get_secgroup_conj_id_and_priority(security_group))

        self.mod_flow(table_id=table_id,
                      match=self.parser.OFPMatch(conj_id=conj_id),
                      command=ofproto.OFPFC_DELETE,
                      )

    def _uninstall_security_group_flow(self, security_group):
        self._uninstall_security_group_permit_flow(
            security_group, EGRESS_SECURITY_GROUP_TABLE)
        self._uninstall_security_group_permit_flow(
            security_group, INGRESS_SECURITY_GROUP_TABLE)

        for rule in security_group.rules:
            self.remove_security_group_rule(security_group, rule)

    def _get_rule_l2_l4_matches(self, rule):
        l2_match = self._get_rule_l2_match(rule)
        l4_matches = self._get_rule_l4_matches(rule)
        if not l4_matches:
            matches = [l2_match]
        else:
            for match in l4_matches:
                match.update(l2_match)
            matches = l4_matches
        return matches

    def _install_associating_flow(self, security_group,
                                  lport, register, table_id):
        if self._is_sg_not_associated_with_local_port(security_group):
            return

        lport_classify_match = {register: lport.unique_key}

        conj_id, priority = (
            self._get_secgroup_conj_id_and_priority(security_group))

        match = self.parser.OFPMatch(**lport_classify_match)
        actions = [self.parser.NXActionConjunction(clause=0,
                                                   n_clauses=2,
                                                   id_=conj_id)]
        self.mod_flow(
            actions=actions,
            table_id=table_id,
            priority=priority,
            match=match)

    def _uninstall_associating_flow(self, security_group,
                                    lport, register, table_id):
        if self._is_sg_not_associated_with_local_port(security_group):
            return

        lport_classify_match = {register: lport.unique_key}

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group)

        match = self.parser.OFPMatch(**lport_classify_match)
        self.mod_flow(
            table_id=table_id,
            priority=priority,
            match=match,
            command=self.ofproto.OFPFC_DELETE_STRICT)

    def _install_associating_flows(self, security_group, lport):
        self._install_associating_flow(security_group, lport,
                                       'reg6', EGRESS_SECURITY_GROUP_TABLE)
        self._install_associating_flow(security_group, lport,
                                       'reg7', INGRESS_SECURITY_GROUP_TABLE)

    def _uninstall_associating_flows(self, security_group, lport):
        self._uninstall_associating_flow(security_group, lport,
                                         'reg6', EGRESS_SECURITY_GROUP_TABLE)
        self._uninstall_associating_flow(security_group, lport,
                                         'reg7', INGRESS_SECURITY_GROUP_TABLE)

    def _install_connection_track_flow(self, lport, register, priority_offset):
        actions = [self.parser.NXActionCT(
            actions=[],
            alg=0,
            flags=0,
            recirc_table=CONNTRACK_RESULT_TABLE,
            zone_ofs_nbits=const.SG_TRACKING_ZONE,
            zone_src='',
        ), ]

        match = {register: lport.unique_key}
        self._install_ipv4_ipv6_rules(
            table_id=CONNTRACK_TABLE,
            match_items=match,
            priority=const.PRIORITY_MEDIUM + priority_offset,
            actions=actions
        )

    def _uninstall_connection_track_flow(self, lport, register,
                                         priority_offset=0):
        ofproto = self.ofproto
        unique_key = lport.unique_key
        match = {register: unique_key}

        self._install_ipv4_ipv6_rules(
            table_id=CONNTRACK_TABLE,
            match_items=match,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM + priority_offset
        )

    def _install_connection_track_flows(self, lport):
        self._install_connection_track_flow(lport, 'reg6', 1)
        self._install_connection_track_flow(lport, 'reg7', 0)

    def _uninstall_connection_track_flows(self, lport):
        self._uninstall_connection_track_flow(lport, 'reg6', 1)
        self._uninstall_connection_track_flow(lport, 'reg7', 0)

    def _disassociate_remote_secgroup_lport(self, rule, lport):
        if rule.direction == DIRECTION_INGRESS:
            table_id = INGRESS_SECURITY_GROUP_TABLE
            register = 'reg6'
        else:
            table_id = EGRESS_SECURITY_GROUP_TABLE
            register = 'reg7'
        match = {register: lport.unique_key}
        cookie, cookie_mask = self._get_rule_cookie(rule.id)
        # Match by cookie, so priority is not needed
        self.mod_flow(
            cookie=cookie,
            cookie_mask=cookie_mask,
            table_id=table_id,
            match=self.parser.OFPMatch(match),
            command=self.ofproto.OFPFC_DELETE_STRICT
        )

    def _associate_secgroup_rule_lport(self, rule, lport):
        secgroup = self.db_store.get_one(
            sg_model.SecurityGroup(id=rule.security_group_id))
        if self._is_sg_not_associated_with_local_port(secgroup):
            return
        matches = self._get_rule_l2_l4_matches(rule)
        parser = self.parser
        cookie, cookie_mask = self._get_rule_cookie(rule.id)
        conj_id, priority = self._get_secgroup_conj_id_and_priority(secgroup)

        # Add new flow
        actions = [parser.NXActionConjunction(clause=1,
                                              n_clauses=2,
                                              id_=conj_id)]
        # XXX Code duplication. Get table_id by method
        if rule.direction == DIRECTION_INGRESS:
            table_id = INGRESS_SECURITY_GROUP_TABLE
            register = 'reg6'
        else:
            table_id = EGRESS_SECURITY_GROUP_TABLE
            register = 'reg7'
        for match in matches:
            match[register] = lport.unique_key
            ofpmatch = parser.OFPMatch(**match)
            self.mod_flow(
                cookie=cookie,
                cookie_mask=cookie_mask,
                actions=actions,
                table_id=table_id,
                priority=priority,
                match=ofpmatch)

    def _get_remote_ports(self, remote_group_id):
        remote_port_ids = self.secgroup_associate_local_ports.get(
            remote_group_id)
        if not remote_port_ids:
            return []
        remote_ports = [self.db_store.get_one(l2.LogicalPort(id=lport_id))
                        for lport_id in remote_port_ids]
        return remote_ports

    def _install_security_group_rule_flows(self, secgroup, secgroup_rule):
        conj_id, priority = self._get_secgroup_conj_id_and_priority(secgroup)

        # Conj 2/2 : l2, l3, l4, source/destination
        matches = self._get_rule_l2_l4_matches(secgroup_rule)
        remote_group_id = secgroup_rule.remote_group_id
        remote_ip_prefix = secgroup_rule.remote_ip_prefix
        ethertype = secgroup_rule.ethertype
        if remote_group_id:
            remote_ports = self._get_remote_ports(remote_group_id)
            if not remote_ports:
                return
            # XXX Code duplication. Get table_id and register by method
            if secgroup_rule.direction == DIRECTION_INGRESS:
                register = 'reg6'
            else:
                register = 'reg7'
            new_matches = []
            for remote_port, match in itertools.product(remote_ports, matches):
                new_match = copy.copy(match)
                new_match[register] = remote_port.unique_key
                new_matches.append(new_match)
            matches = new_matches
        elif remote_ip_prefix:
            ip_match_item = self._get_l3_match_item(
                ethertype, secgroup_rule.direction)
            if not ip_match_item:
                LOG.error("wrong ethernet type")
                return

            if (remote_ip_prefix.version !=
                    utils.ethertype_to_ip_version(ethertype)):
                LOG.error("mismatch ethernet type and rule ip prefix")
                return

            for match in matches:
                match[ip_match_item] = remote_ip_prefix

        parser = self.parser

        if secgroup_rule.direction == DIRECTION_INGRESS:
            table_id = INGRESS_SECURITY_GROUP_TABLE
        else:
            table_id = EGRESS_SECURITY_GROUP_TABLE

        actions = [parser.NXActionConjunction(clause=1,
                                              n_clauses=2,
                                              id_=conj_id)]
        cookie, cookie_mask = self._get_rule_cookie(secgroup_rule.id)
        for match in matches:
            ofpmatch = parser.OFPMatch(**match)
            self.mod_flow(
                cookie=cookie,
                cookie_mask=cookie_mask,
                actions=actions,
                table_id=table_id,
                priority=priority,
                match=ofpmatch)

    def _uninstall_security_group_rule_flows(self, secgroup_rule):
        # uninstall rule flows by its cookie
        ofproto = self.ofproto

        direction = secgroup_rule.direction
        if direction == DIRECTION_INGRESS:
            table_id = INGRESS_SECURITY_GROUP_TABLE
        else:
            table_id = EGRESS_SECURITY_GROUP_TABLE

        cookie, cookie_mask = self._get_rule_cookie(secgroup_rule.id)
        self.mod_flow(
            cookie=cookie,
            cookie_mask=cookie_mask,
            table_id=table_id,
            command=ofproto.OFPFC_DELETE)

    def _install_conntrack_prepare(self):
        """
        Prepare the packet for connection tracking. Push IPs to stack, and
        replace with unique keys.
        """
        # IPv4
        match = {'eth_type': ether.ETH_TYPE_IP}
        actions = [
            self.parser.NXActionStackPush(field='ipv4_src', start=0, end=32),
            self.parser.NXActionStackPush(field='ipv4_dst', start=0, end=32),
            self.parser.NXActionRegMove(
                src_field='reg6',
                dst_field='ipv4_src',
                n_bits=32,
            ),
            self.parser.NXActionRegLoad(
                ofs_nbits=nicira_ext.ofs_nbits(31, 31),
                dst="ipv4_src",
                value=1,
            ),
            self.parser.NXActionRegMove(
                src_field='reg7',
                dst_field='ipv4_dst',
                n_bits=32,
            ),
            self.parser.NXActionRegLoad(
                ofs_nbits=nicira_ext.ofs_nbits(31, 31),
                dst="ipv4_dst",
                value=1,
            ),
        ]
        inst = [
            self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, actions),
            self.parser.OFPInstructionGotoTable(CONNTRACK_TABLE),
        ]
        self.mod_flow(
            table_id=CONNTRACK_PREPARE_TABLE,
            match=self.parser.OFPMatch(**match),
            inst=inst
        )

        # IPv6
        match = {'eth_type': ether.ETH_TYPE_IPV6}
        actions = [
            self.parser.NXActionStackPush(field='ipv6_src', start=0, end=128),
            self.parser.NXActionStackPush(field='ipv6_dst', start=0, end=128),
            self.parser.NXActionRegMove(
                src_field='reg6',
                dst_field='ipv6_src',
                n_bits=32,
            ),
            self.parser.NXActionRegLoad(
                ofs_nbits=nicira_ext.ofs_nbits(127, 127),
                dst="ipv6_src",
                value=1,
            ),
            self.parser.NXActionRegMove(
                src_field='reg7',
                dst_field='ipv6_dst',
                n_bits=32,
            ),
            self.parser.NXActionRegLoad(
                ofs_nbits=nicira_ext.ofs_nbits(127, 127),
                dst="ipv6_dst",
                value=1,
            ),
        ]
        inst = [
            self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, actions),
            self.parser.OFPInstructionGotoTable(CONNTRACK_TABLE),
        ]
        self.mod_flow(
            table_id=CONNTRACK_PREPARE_TABLE,
            match=self.parser.OFPMatch(**match),
            inst=inst
        )

    def _install_conntrack_result(self):
        """
        Handle immediate conntrack result. Basically, commit new packets, and
        discard invalid ones
        """
        # inv state, drop
        invalid_ct_state_flag = const.CT_STATE_TRK | const.CT_STATE_INV
        match = self.parser.OFPMatch(ct_state=(invalid_ct_state_flag,
                                               invalid_ct_state_flag))
        self.mod_flow(
             table_id=CONNTRACK_RESULT_TABLE,
             priority=const.PRIORITY_CT_STATE,
             match=match)

        # commit new packets
        new_state_flag = const.CT_STATE_NEW
        new_valid_flag_mask = const.CT_STATE_NEW | const.CT_STATE_INV
        match_items = {'ct_state': (new_state_flag, new_valid_flag_mask)}
        actions = [
            self.parser.NXActionCT(actions=[],
                                   alg=0,
                                   flags=const.CT_FLAG_COMMIT,
                                   recirc_table=CONNTRACK_CLEANUP_TABLE,
                                   zone_ofs_nbits=const.SG_TRACKING_ZONE,
                                   zone_src='',
                                   ),
        ]

        self._install_ipv4_ipv6_rules(table_id=CONNTRACK_RESULT_TABLE,
                                      actions=actions,
                                      match_items=match_items,
                                      priority=const.PRIORITY_CT_STATE)

        # Default: fall through
        self.add_flow_go_to_table(CONNTRACK_RESULT_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  CONNTRACK_CLEANUP_TABLE)

    def _install_conntrack_preparation_cleanup_ipv46(self, match,
                                                     next_table, priority):

        ipv4_match = {'eth_type': ether.ETH_TYPE_IP}
        ipv4_actions = [
            self.parser.NXActionStackPop(field='ipv4_dst', start=0, end=32),
            self.parser.NXActionStackPop(field='ipv4_src', start=0, end=32),
        ]
        ipv6_match = {'eth_type': ether.ETH_TYPE_IPV6}
        ipv6_actions = [
            self.parser.NXActionStackPop(field='ipv6_dst', start=0, end=128),
            self.parser.NXActionStackPop(field='ipv6_src', start=0, end=128),
        ]
        # IPv4:
        ipv4_match.update(match)
        inst = [
            self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, ipv4_actions),
            self.parser.OFPInstructionGotoTable(next_table),
        ]
        self.mod_flow(table_id=CONNTRACK_CLEANUP_TABLE,
                      match=self.parser.OFPMatch(**ipv4_match),
                      inst=inst,
                      priority=priority,
                      )
        # IPv6:
        ipv6_match.update(match)
        inst = [
            self.parser.OFPInstructionActions(
                self.ofproto.OFPIT_APPLY_ACTIONS, ipv6_actions),
            self.parser.OFPInstructionGotoTable(next_table),
        ]
        self.mod_flow(table_id=CONNTRACK_CLEANUP_TABLE,
                      match=self.parser.OFPMatch(**ipv6_match),
                      inst=inst,
                      priority=priority,
                      )

    def _install_conntrack_preparation_cleanup(self):
        """
        Clean up conntrack preparation (restore L3), and send packet on its
        way: Through security group rules for new packets, and accept path
        for established and related packets.
        """
        # new - go to next table for sec group processing
        match_new_conn = {'ct_state': (const.CT_STATE_NEW, const.CT_STATE_NEW)}
        self._install_conntrack_preparation_cleanup_ipv46(
            match_new_conn, EGRESS_SECURITY_GROUP_TABLE, const.PRIORITY_MEDIUM)

        # related, established - skip sec group (no need)
        match_rel_conn = {'ct_state': (const.CT_STATE_REL, const.CT_STATE_REL)}
        self._install_conntrack_preparation_cleanup_ipv46(
            match_rel_conn, SECURITY_GROUP_EXIT_TABLE, const.PRIORITY_HIGH)

        match_est_conn = {'ct_state': (const.CT_STATE_EST, const.CT_STATE_EST)}
        self._install_conntrack_preparation_cleanup_ipv46(
            match_est_conn, SECURITY_GROUP_EXIT_TABLE, const.PRIORITY_HIGH + 1)

    def _install_env_init_flow(self):
        self._install_conntrack_prepare()
        self._install_conntrack_preparation_cleanup()
        self._install_conntrack_result()

        # defaults of sg-table to drop packet
        self.mod_flow(
             table_id=EGRESS_SECURITY_GROUP_TABLE,
             priority=const.PRIORITY_DEFAULT)

        self.mod_flow(
             table_id=INGRESS_SECURITY_GROUP_TABLE,
             priority=const.PRIORITY_DEFAULT)

    def switch_features_handler(self, ev):
        self._install_env_init_flow()
        self.secgroup_associate_local_ports.clear()
        self.remote_secgroup_ref.clear()

    def _get_security_rule_mapping(self, lrule_id):
        rule_id = self.secgroup_rule_mappings.get(lrule_id)
        if rule_id is not None:
            return rule_id
        else:
            self.next_secgroup_rule_id += 1
            # TODO(ding bo) verify self.next_network_id didn't wrap
            self.secgroup_rule_mappings[lrule_id] = self.next_secgroup_rule_id
            return self.next_secgroup_rule_id

    def _get_secgroup_conj_id_and_priority(self, secgroup):
        sg_unique_key = secgroup.unique_key
        return sg_unique_key, (SG_PRIORITY_OFFSET + sg_unique_key)

    def _associate_secgroup_lport(self, secgroup, lport):
        # update the flows representing those rules each of which specifies
        #  this security group as its parameter
        # of remote group.
        secrules = self.remote_secgroup_ref[secgroup.id]
        for rule in secrules.values():
            self._associate_secgroup_rule_lport(rule, lport)

    def _disassociate_secgroup_lport(self, secgroup, lport):
        # update the record of aggregate addresses of ports associated
        # with this security group.
        secrules = self.remote_secgroup_ref[secgroup.id]
        for rule in secrules.values():
            self._disassociate_remote_secgroup_lport(rule, lport)

    def _add_local_port_associating(self, lport, secgroup):
        LOG.debug('_add_local_port_associating: Enter: lport: %s', lport)
        LOG.debug('_add_local_port_associating: Enter: secgroup: %s', secgroup)
        # update the record of ports associated with this security group.
        associate_ports = self.secgroup_associate_local_ports.get(secgroup.id)
        if associate_ports is None:
            self.secgroup_associate_local_ports[secgroup.id] = [lport.id]
            self._install_security_group_flows(secgroup)
        elif lport.id not in associate_ports:
            associate_ports.append(lport.id)

        self._associate_secgroup_lport(secgroup, lport)

        # install associating flow
        self._install_associating_flows(secgroup, lport)

    def _remove_local_port_associating(self, lport, secgroup):
        # uninstall associating flow
        self._uninstall_associating_flows(secgroup, lport)

        self._disassociate_secgroup_lport(secgroup, lport)

        # update the record of ports associated with this security group.
        # XXX Revisit
        associate_ports = \
            self.secgroup_associate_local_ports.get(secgroup.id)
        if associate_ports is not None:
            if lport.id in associate_ports:
                associate_ports.remove(lport.id)
                if len(associate_ports) == 0:
                    self._uninstall_security_group_flow(secgroup)
                    del self.secgroup_associate_local_ports[secgroup.id]

    def _get_added_and_removed_and_unchanged_secgroups(self, secgroups,
                                                       original_secgroups):
        added_secgroups = []
        unchanged_secgroups = []
        removed_secgroups = list(original_secgroups)

        for item in secgroups:
            if item in removed_secgroups:
                removed_secgroups.remove(item)
                unchanged_secgroups.append(item)
            else:
                added_secgroups.append(item)

        return added_secgroups, removed_secgroups, unchanged_secgroups

    def _install_skip_ingress_rule(self, lport):
        self.add_flow_go_to_table(
            INGRESS_SECURITY_GROUP_TABLE,
            const.PRIORITY_DEFAULT + 1,
            SECURITY_GROUP_EXIT_TABLE,
            match=self.parser.OFPMatch(reg7=lport.unique_key),
        )

    def _uninstall_skip_ingress_rule(self, lport):
        self.mod_flow(
            table_id=INGRESS_SECURITY_GROUP_TABLE,
            priority=const.PRIORITY_DEFAULT + 1,
            match=self.parser.OFPMatch(reg7=lport.unique_key),
            command=self.ofproto.OFPFC_DELETE_STRICT,
        )

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_REMOTE)
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _remove_local_port(self, lport):
        secgroups = lport.security_groups
        if not secgroups:
            self._uninstall_skip_ingress_rule(lport)
            return

        # uninstall ct table
        self._uninstall_connection_track_flows(lport)

        for secgroup in secgroups:
            self._remove_local_port_associating(lport, secgroup)

        self._delete_conntrack_for_lport(lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_REMOTE_UPDATED)
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_UPDATED)
    def update_local_port(self, lport, original_lport):
        secgroups = lport.security_groups
        original_secgroups = original_lport.security_groups

        added_secgroups, removed_secgroups, unchanged_secgroups = \
            self._get_added_and_removed_and_unchanged_secgroups(
                secgroups, original_secgroups)

        if not secgroups and original_secgroups:
            # uninstall ct table
            self._uninstall_connection_track_flows(lport)
            self._install_skip_ingress_rule(lport)

        for secgroup in added_secgroups:
            self._add_local_port_associating(lport, secgroup)

        for secgroup in removed_secgroups:
            self._remove_local_port_associating(original_lport, secgroup)

        if secgroups and not original_secgroups:
            # install ct table
            self._install_connection_track_flows(lport)
            self._uninstall_skip_ingress_rule(lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_REMOTE)
    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _add_local_port(self, lport):
        secgroups = lport.security_groups
        if not secgroups:
            self._install_skip_ingress_rule(lport)
            return

        for secgroup in secgroups:
            self._add_local_port_associating(lport, secgroup)

        # install ct table
        self._install_connection_track_flows(lport)

    def _is_sg_not_associated_with_local_port(self, secgroup):
        return self.secgroup_associate_local_ports.get(secgroup.id) is None

    @df_base_app.register_event(sg_model.SecurityGroup,
                                model_constants.EVENT_CREATED)
    def add_security_group(self, secgroup):
        for new_rule in secgroup.rules:
            self.add_security_group_rule(secgroup, new_rule)

    @df_base_app.register_event(sg_model.SecurityGroup,
                                model_constants.EVENT_UPDATED)
    def update_security_group(self, new_secgroup, old_secgroup):
        new_secgroup_rules = new_secgroup.rules
        old_secgroup_rules = copy.copy(old_secgroup.rules)
        for new_rule in new_secgroup_rules:
            if new_rule not in old_secgroup_rules:
                self.add_security_group_rule(new_secgroup, new_rule)
            else:
                old_secgroup_rules.remove(new_rule)

        for old_rule in old_secgroup_rules:
            self.remove_security_group_rule(old_secgroup, old_rule)

    @df_base_app.register_event(sg_model.SecurityGroup,
                                model_constants.EVENT_DELETED)
    def delete_security_group(self, secgroup):
        for rule in secgroup.rules:
            self.remove_security_group_rule(secgroup, rule)
        self.remote_secgroup_ref.pop(secgroup.id, None)

    @df_base_app.register_event(sg_model.SecurityGroupRule,
                                model_constants.EVENT_CREATED)
    def add_security_group_rule(self, secgroup, secgroup_rule):
        if self._is_sg_not_associated_with_local_port(secgroup):
            LOG.debug("Security group %s wasn't associated with a local port",
                      secgroup)
            return

        LOG.info("Add a rule %(rule)s to security group %(secgroup)s",
                 {'rule': secgroup_rule, 'secgroup': secgroup.id})

        # update the record of rules each of which specifies a same security
        #  group as its parameter of remote group.
        remote_group_id = secgroup_rule.remote_group_id
        if remote_group_id is not None:
            associate_rules = self.remote_secgroup_ref[remote_group_id]
            associate_rules[secgroup_rule.id] = secgroup_rule
        self._install_security_group_rule_flows(secgroup, secgroup_rule)

    @df_base_app.register_event(sg_model.SecurityGroupRule,
                                model_constants.EVENT_DELETED)
    def remove_security_group_rule(self, secgroup, secgroup_rule):
        if self._is_sg_not_associated_with_local_port(secgroup):
            LOG.debug("Security group %s wasn't associated with a local port",
                      secgroup.id)
            return

        LOG.info("Remove a rule %(rule)s to security group %(secgroup)s",
                 {'rule': secgroup_rule, 'secgroup': secgroup.id})

        conj_id, priority = self._get_secgroup_conj_id_and_priority(secgroup)

        # update the record of rules each of which specifies a same security
        # group as its parameter of remote group.
        remote_group_id = secgroup_rule.remote_group_id
        if remote_group_id is not None:
            associate_rules = self.remote_secgroup_ref[remote_group_id]
            associate_rules.pop(secgroup_rule.id)

        self._uninstall_security_group_rule_flows(secgroup_rule)

    def _delete_conntrack_for_lport(self, lport):
        has_ipv4 = False
        has_ipv6 = False
        for ip in lport.all_ips:
            has_ipv4 = has_ipv4 or (ip.version == n_const.IP_VERSION_4)
            has_ipv6 = has_ipv6 or (ip.version == n_const.IP_VERSION_6)
        if has_ipv4:
            ip = (netaddr.IPAddress(lport.unique_key) |
                  netaddr.IPAddress('128.0.0.0'))
            conntrack.delete_conntrack_entries_by_filter(
                nw_src=ip, zone=const.SG_TRACKING_ZONE)
            conntrack.delete_conntrack_entries_by_filter(
                nw_dst=ip, zone=const.SG_TRACKING_ZONE)
        if has_ipv6:
            ip = (netaddr.IPAddress(lport.unique_key, version=6) |
                  netaddr.IPAddress('1::'))
            conntrack.delete_conntrack_entries_by_filter(
                ethertype='IPv6', nw_src=ip, zone=const.SG_TRACKING_ZONE)
            conntrack.delete_conntrack_entries_by_filter(
                ethertype='IPv6', nw_dst=ip, zone=const.SG_TRACKING_ZONE)
