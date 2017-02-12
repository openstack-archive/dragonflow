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
import netaddr
from neutron_lib import constants as n_const
from oslo_log import log
from ryu.ofproto import ether

from dragonflow._i18n import _LI, _LW, _LE
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils
from dragonflow.controller import df_base_app
from dragonflow.db import models


LOG = log.getLogger(__name__)

SG_CT_STATE_MASK = const.CT_STATE_NEW | const.CT_STATE_EST | \
                   const.CT_STATE_REL | const.CT_STATE_INV | const.CT_STATE_TRK
SG_PRIORITY_OFFSET = 2
COOKIE_NAME = 'sg rule'

DEST_FIELD_NAME_BY_PROTOCOL_NUMBER = {
    n_const.PROTO_NUM_TCP: 'tcp_dst',
    n_const.PROTO_NUM_UDP: 'udp_dst',
}

PROTOCOL_NUMBER_BY_NAME = {
    n_const.PROTO_NAME_AH: n_const.PROTO_NUM_AH,
    n_const.PROTO_NAME_DCCP: n_const.PROTO_NUM_DCCP,
    n_const.PROTO_NAME_EGP: n_const.PROTO_NUM_EGP,
    n_const.PROTO_NAME_ESP: n_const.PROTO_NUM_ESP,
    n_const.PROTO_NAME_GRE: n_const.PROTO_NUM_GRE,
    n_const.PROTO_NAME_ICMP: n_const.PROTO_NUM_ICMP,
    n_const.PROTO_NAME_IGMP: n_const.PROTO_NUM_IGMP,
    n_const.PROTO_NAME_IPV6_ENCAP: n_const.PROTO_NUM_IPV6_ENCAP,
    n_const.PROTO_NAME_IPV6_FRAG: n_const.PROTO_NUM_IPV6_FRAG,
    n_const.PROTO_NAME_IPV6_ICMP: n_const.PROTO_NUM_IPV6_ICMP,
    n_const.PROTO_NAME_IPV6_ICMP_LEGACY: n_const.PROTO_NUM_IPV6_ICMP,
    n_const.PROTO_NAME_IPV6_NONXT: n_const.PROTO_NUM_IPV6_NONXT,
    n_const.PROTO_NAME_IPV6_OPTS: n_const.PROTO_NUM_IPV6_OPTS,
    n_const.PROTO_NAME_IPV6_ROUTE: n_const.PROTO_NUM_IPV6_ROUTE,
    n_const.PROTO_NAME_OSPF: n_const.PROTO_NUM_OSPF,
    n_const.PROTO_NAME_PGM: n_const.PROTO_NUM_PGM,
    n_const.PROTO_NAME_RSVP: n_const.PROTO_NUM_RSVP,
    n_const.PROTO_NAME_SCTP: n_const.PROTO_NUM_SCTP,
    n_const.PROTO_NAME_TCP: n_const.PROTO_NUM_TCP,
    n_const.PROTO_NAME_UDP: n_const.PROTO_NUM_UDP,
    n_const.PROTO_NAME_UDPLITE: n_const.PROTO_NUM_UDPLITE,
    n_const.PROTO_NAME_VRRP: n_const.PROTO_NUM_VRRP,
}


class SGApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(SGApp, self).__init__(*args, **kwargs)
        self.secgroup_rule_mappings = {}
        self.next_secgroup_rule_id = 0
        self.remote_secgroup_ref = {}
        self.secgroup_associate_local_ports = {}
        self.secgroup_aggregate_addresses = collections.defaultdict(
            netaddr.IPSet
        )
        self.secgroup_ip_refs = collections.defaultdict(set)
        self.register_local_cookie_bits(COOKIE_NAME, 32)

    @staticmethod
    def _get_cidr_difference(cidr_set, new_cidr_set):
        new_cidr_list = new_cidr_set.iter_cidrs()
        old_cidr_list = cidr_set.iter_cidrs()

        added_cidr = set(new_cidr_list) - set(old_cidr_list)
        removed_cidr = set(old_cidr_list) - set(new_cidr_list)
        return added_cidr, removed_cidr

    @staticmethod
    def _get_cidr_changes_after_removing_addresses(cidr_set, address_list):
        """cidr_set - IPSet
           address_list - IPAddress or string list
        """
        new_cidr_set = cidr_set - netaddr.IPSet(address_list)
        added_cidr, removed_cidr = SGApp._get_cidr_difference(cidr_set,
                                                              new_cidr_set)
        return new_cidr_set, added_cidr, removed_cidr

    @staticmethod
    def _get_cidr_changes_after_adding_addresses(cidr_set, address_list):
        """cidr_set - IPSet
           address_list - IPAddress or string list
        """
        new_cidr_set = cidr_set | netaddr.IPSet(address_list)
        added_cidr, removed_cidr = SGApp._get_cidr_difference(cidr_set,
                                                              new_cidr_set)
        return new_cidr_set, added_cidr, removed_cidr

    @staticmethod
    def _get_cidr_changes_after_updating_addresses(cidr_set, addresses_to_add,
                                                   addresses_to_remove):
        """cidr_set - IPSet
           addresses_to_add - IPAddress or string list
           addresses_to_remove - IPAddress or string list
        """
        new_cidr_set = ((cidr_set | netaddr.IPSet(addresses_to_add)) -
                        (netaddr.IPSet(addresses_to_remove)))
        added_cidr, removed_cidr = SGApp._get_cidr_difference(cidr_set,
                                                              new_cidr_set)
        return new_cidr_set, added_cidr, removed_cidr

    @staticmethod
    def _get_port_match_list_from_port_range(port_range_min, port_range_max):
        port_range = netaddr.IPRange(port_range_min, port_range_max)
        ports_match_list = []
        for cidr in port_range.cidrs():
            port_num = int(cidr.network) & 0xffff
            mask = int(cidr.netmask) & 0xffff
            ports_match_list.append((port_num, mask))
        return ports_match_list

    @staticmethod
    def _get_network_and_mask(cidr):
        result = netaddr.IPNetwork(cidr)
        return (int(result.network), int(result.netmask))

    def _protocol_number_by_name(self, name):
        return PROTOCOL_NUMBER_BY_NAME.get(name) or int(name)

    def _get_rule_flows_match_except_net_addresses(self, secgroup_rule):
        """
        Create the match object for the security group rule given in
        secgroup_rule (type SecurityGroupRule).
        """
        result_base = {}
        ethertype = secgroup_rule.get_ethertype()
        if ethertype == n_const.IPv4:
            result_base['eth_type'] = ether.ETH_TYPE_IP
        elif ethertype == n_const.IPv6:
            LOG.warning(
                _LW("IPv6 in security group rules is not yet supported")
            )
            result_base['eth_type'] = ether.ETH_TYPE_IPV6
            return [result_base]
        protocol_name = secgroup_rule.get_protocol()
        if not protocol_name:
            return [result_base]
        protocol = self._protocol_number_by_name(protocol_name)
        result_base["ip_proto"] = protocol
        port_range_min = secgroup_rule.get_port_range_min()
        port_range_max = secgroup_rule.get_port_range_max()
        if protocol == n_const.PROTO_NUM_ICMP:
            if port_range_min:
                result_base['icmpv4_type'] = int(port_range_min)
            if port_range_max:
                result_base['icmpv4_code'] = int(port_range_max)
            results = [result_base]
        elif ((not port_range_min and not port_range_max) or
              (int(port_range_min) == const.MIN_PORT and
               int(port_range_max) == const.MAX_PORT)):
            results = [result_base]
        else:
            port_match_list = SGApp._get_port_match_list_from_port_range(
                port_range_min, port_range_max)
            key = DEST_FIELD_NAME_BY_PROTOCOL_NUMBER[protocol]
            results = []
            for port_match in port_match_list:
                result = result_base.copy()
                result[key] = port_match
                results.append(result)
        return results

    def _get_rule_cookie(self, rule_id):
        return self.get_local_cookie(COOKIE_NAME, rule_id)

    def _inc_ip_reference_and_check(self, secgroup_id, ip, lport_id):
        """
        Increasing the reference count of a IP address in a security group and
        return true if it is the first lport with this IP address associated
        with the security group.
        """
        is_first = False
        key = (secgroup_id, ip)
        ip_ref = self.secgroup_ip_refs[key]
        if not ip_ref:
            # It is the first lport with this IP address associated with the
            # security group
            is_first = True
        ip_ref.add(lport_id)

        return is_first

    def _dec_ip_reference_and_check(self, secgroup_id, ip, lport_id):
        """
        Decreasing the reference count of a IP address in a security group and
        return true if it is the last lport with this IP address associated
        with the security group.
        """
        key = (secgroup_id, ip)
        lport_id_set = self.secgroup_ip_refs.get(key)
        if (lport_id_set is not None) and (lport_id in lport_id_set):
            lport_id_set.remove(lport_id)
            if len(lport_id_set) == 0:
                self.secgroup_ip_refs.pop(key, None)
                return True

        return False

    def _get_ips_in_logical_port(self, lport):
        """
        Get all IP addresses which were bound with this lport as fixed IP
        address or a IP address in allowed address pairs.
        """
        ips = set()
        fixed_ip = lport.get_ip()
        if netaddr.IPNetwork(fixed_ip).version == 4:
            ips.add(fixed_ip)
        else:
            LOG.warning(_LW("No support for non IPv4 protocol, the IP"
                            "address %(ip)s of %(lport)s was ignored."),
                        {'ip': fixed_ip, 'lport': lport.get_id()})

        allowed_address_pairs = lport.get_allowed_address_pairs()
        if allowed_address_pairs is not None:
            for pair in allowed_address_pairs:
                ip = pair["ip_address"]
                if netaddr.IPNetwork(ip).version == 4:
                    ips.add(ip)
                else:
                    LOG.warning(
                        _LW("No support for non IPv4 protocol, the address "
                            "%(ip)s in allowed address pairs of lport "
                            "%(lport)s was ignored."),
                        {'ip': ip, 'lport': lport.get_id()})
        return ips

    def _get_lport_added_ips_for_secgroup(self, secgroup_id, lport):
        """
        Get added lport IP addresses to the security group after a check for
        filtering duplicated IP addresses with other proceeded lports.
        """
        added_ips = []
        ips = self._get_ips_in_logical_port(lport)
        for ip in ips:
            if self._inc_ip_reference_and_check(secgroup_id, ip,
                                                lport.get_id()):
                added_ips.append(ip)

        return added_ips

    def _get_lport_removed_ips_for_secgroup(self, secgroup_id, lport):
        """
        Get removed lport IP addresses from the security group after a check
        for filtering the IP addresses also bound with other lports in the
        security group.
        """
        removed_ips = []
        ips = self._get_ips_in_logical_port(lport)
        for ip in ips:
            if self._dec_ip_reference_and_check(secgroup_id, ip,
                                                lport.get_id()):
                removed_ips.append(ip)

        return removed_ips

    def _get_lport_updated_ips_for_secgroup(self, secgroup_id, lport,
                                            original_lport):
        """
        Get added and removed lport IP addresses in the security group after
        the check for filtering the IP addresses which could conflicting with
        other lports.
        """
        added_ips = []
        removed_ips = []

        ips = self._get_ips_in_logical_port(lport)
        original_ips = self._get_ips_in_logical_port(original_lport)

        for ip in ips:
            if (ip not in original_ips) and self._inc_ip_reference_and_check(
                    secgroup_id, ip, lport.get_id()):
                added_ips.append(ip)

        for ip in original_ips:
            if (ip not in ips) and self._dec_ip_reference_and_check(
                    secgroup_id, ip, lport.get_id()):
                removed_ips.append(ip)

        return added_ips, removed_ips

    def _install_security_group_permit_flow_by_direction(self,
                                                         security_group_id,
                                                         direction):
        if self._is_sg_not_associated_with_local_port(security_group_id):
            return

        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            recirc_table = const.INGRESS_DISPATCH_TABLE
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            recirc_table = const.SERVICES_CLASSIFICATION_TABLE

        parser = self.parser
        ofproto = self.ofproto

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, conj_id=conj_id)
        actions = [parser.NXActionCT(actions=[],
                                     alg=0,
                                     flags=const.CT_FLAG_COMMIT,
                                     recirc_table=recirc_table,
                                     zone_ofs_nbits=15,
                                     zone_src=const.CT_ZONE_REG)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=table_id,
            priority=priority,
            match=match)

    def _install_security_group_flows(self, security_group_id):
        self._install_security_group_permit_flow_by_direction(
            security_group_id, 'ingress')
        self._install_security_group_permit_flow_by_direction(
            security_group_id, 'egress')

        secgroup = self.db_store.get_security_group(security_group_id)
        if secgroup is not None:
            for rule in secgroup.get_rules():
                self.add_security_group_rule(secgroup, rule)

    def _uninstall_security_group_permit_flow_by_direction(self,
                                                           security_group_id,
                                                           direction):
        if self._is_sg_not_associated_with_local_port(security_group_id):
            return

        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE

        parser = self.parser
        ofproto = self.ofproto

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, conj_id=conj_id)
        self.mod_flow(
            table_id=table_id,
            match=match,
            command=ofproto.OFPFC_DELETE)

    def _uninstall_security_group_flow(self, security_group_id):
        self._uninstall_security_group_permit_flow_by_direction(
            security_group_id, 'ingress')
        self._uninstall_security_group_permit_flow_by_direction(
            security_group_id, 'egress')

        secgroup = self.db_store.get_security_group(security_group_id)
        if secgroup is not None:
            for rule in secgroup.get_rules():
                self.remove_security_group_rule(secgroup, rule)

    def _install_associating_flow_by_direction(self, security_group_id,
                                               lport, direction):
        if self._is_sg_not_associated_with_local_port(security_group_id):
            return

        parser = self.parser
        ofproto = self.ofproto

        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            tunnel_key = lport.get_unique_key()
            lport_classify_match = {"reg7": tunnel_key}
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            ofport = lport.get_external_value('ofport')
            lport_classify_match = {"in_port": ofport}

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)

        match = parser.OFPMatch(ct_state=(const.CT_STATE_TRK |
                                          const.CT_STATE_NEW,
                                          SG_CT_STATE_MASK),
                                **lport_classify_match)
        actions = [parser.NXActionConjunction(clause=0,
                                              n_clauses=2,
                                              id_=conj_id)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=table_id,
            priority=priority,
            match=match)

    def _uninstall_associating_flow_by_direction(self, security_group_id,
                                                 lport, direction):
        if self._is_sg_not_associated_with_local_port(security_group_id):
            return

        parser = self.parser
        ofproto = self.ofproto

        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            tunnel_key = lport.get_unique_key()
            lport_classify_match = {"reg7": tunnel_key}
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            ofport = lport.get_external_value('ofport')
            lport_classify_match = {"in_port": ofport}

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)

        match = parser.OFPMatch(ct_state=(const.CT_STATE_TRK |
                                          const.CT_STATE_NEW,
                                          SG_CT_STATE_MASK),
                                **lport_classify_match)

        self.mod_flow(
            table_id=table_id,
            priority=priority,
            match=match,
            command=ofproto.OFPFC_DELETE_STRICT)

    def _install_associating_flows(self, security_group_id, lport):
        self._install_associating_flow_by_direction(security_group_id,
                                                    lport,
                                                    'ingress')
        self._install_associating_flow_by_direction(security_group_id,
                                                    lport,
                                                    'egress')

    def _uninstall_associating_flows(self, security_group_id, lport):
        self._uninstall_associating_flow_by_direction(security_group_id,
                                                      lport,
                                                      'ingress')
        self._uninstall_associating_flow_by_direction(security_group_id,
                                                      lport,
                                                      'egress')

    def _install_connection_track_flow_by_direction(self, lport, direction):
        parser = self.parser
        ofproto = self.ofproto

        if direction == 'ingress':
            pre_table_id = const.INGRESS_CONNTRACK_TABLE
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            tunnel_key = lport.get_unique_key()
            lport_classify_match = {"reg7": tunnel_key}
        else:
            pre_table_id = const.EGRESS_CONNTRACK_TABLE
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            ofport = lport.get_external_value('ofport')
            lport_classify_match = {"in_port": ofport}

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                **lport_classify_match)
        actions = [parser.NXActionCT(actions=[],
                                     alg=0,
                                     flags=0,
                                     recirc_table=table_id,
                                     zone_ofs_nbits=15,
                                     zone_src=const.METADATA_REG)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            inst=inst,
            table_id=pre_table_id,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _uninstall_connection_track_flow_by_direction(self, lport, direction):
        parser = self.parser
        ofproto = self.ofproto

        if direction == 'ingress':
            pre_table_id = const.INGRESS_CONNTRACK_TABLE
            tunnel_key = lport.get_unique_key()
            lport_classify_match = {"reg7": tunnel_key}
        else:
            pre_table_id = const.EGRESS_CONNTRACK_TABLE
            ofport = lport.get_external_value('ofport')
            lport_classify_match = {"in_port": ofport}

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                **lport_classify_match)

        self.mod_flow(
            table_id=pre_table_id,
            match=match,
            command=ofproto.OFPFC_DELETE)

    def _install_connection_track_flows(self, lport):
        self._install_connection_track_flow_by_direction(lport, 'ingress')
        self._install_connection_track_flow_by_direction(lport, 'egress')

    def _uninstall_connection_track_flows(self, lport):
        self._uninstall_connection_track_flow_by_direction(lport, 'ingress')
        self._uninstall_connection_track_flow_by_direction(lport, 'egress')

    def _update_security_group_rule_flows_by_addresses(self,
                                                       secgroup_id,
                                                       secgroup_rule,
                                                       added_cidr,
                                                       removed_cidr):
        if self._is_sg_not_associated_with_local_port(secgroup_id):
            return

        conj_id, priority = self._get_secgroup_conj_id_and_priority(
            secgroup_id)

        parser = self.parser
        ofproto = self.ofproto
        rule_id = self._get_security_rule_mapping(secgroup_rule.get_id())

        match_list = \
            self._get_rule_flows_match_except_net_addresses(secgroup_rule)

        if secgroup_rule.get_ethertype() == n_const.IPv4:
            if secgroup_rule.get_direction() == 'ingress':
                table_id = const.INGRESS_SECURITY_GROUP_TABLE
                ipv4_match_item = "ipv4_src"
            else:
                table_id = const.EGRESS_SECURITY_GROUP_TABLE
                ipv4_match_item = "ipv4_dst"
        elif secgroup_rule.get_ethertype() == n_const.IPv6:
            # not support yet
            LOG.info(_LI("IPv6 rules are not supported yet"))
            return
        else:
            LOG.error(_LE("wrong ethernet type"))
            return

        actions = [parser.NXActionConjunction(clause=1,
                                              n_clauses=2,
                                              id_=conj_id)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]

        for added_cidr_item in added_cidr:
            for match_item in match_list:
                parameters_merge = match_item.copy()
                parameters_merge[ipv4_match_item] = \
                    SGApp._get_network_and_mask(added_cidr_item)
                match = parser.OFPMatch(**parameters_merge)
                cookie, cookie_mask = self._get_rule_cookie(rule_id)
                self.mod_flow(
                    cookie=cookie,
                    cookie_mask=cookie_mask,
                    inst=inst,
                    table_id=table_id,
                    priority=priority,
                    match=match)

        for removed_cidr_item in removed_cidr:
            for match_item in match_list:
                parameters_merge = match_item.copy()
                parameters_merge[ipv4_match_item] = \
                    SGApp._get_network_and_mask(removed_cidr_item)
                match = parser.OFPMatch(**parameters_merge)
                self.mod_flow(
                    table_id=table_id,
                    priority=priority,
                    match=match,
                    command=ofproto.OFPFC_DELETE_STRICT)

    def _install_security_group_rule_flows(self, secgroup_id, secgroup_rule):
        conj_id, priority = self._get_secgroup_conj_id_and_priority(
            secgroup_id)

        parser = self.parser
        ofproto = self.ofproto
        rule_id = self._get_security_rule_mapping(secgroup_rule.get_id())
        remote_group_id = secgroup_rule.get_remote_group_id()
        remote_ip_prefix = secgroup_rule.get_remote_ip_prefix()
        ethertype = secgroup_rule.get_ethertype()

        if secgroup_rule.get_direction() == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            ipv4_match_item = "ipv4_src"
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            ipv4_match_item = "ipv4_dst"

        match_list = \
            self._get_rule_flows_match_except_net_addresses(secgroup_rule)

        actions = [parser.NXActionConjunction(clause=1,
                                              n_clauses=2,
                                              id_=conj_id)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]

        if ethertype == n_const.IPv4:
            addresses_list = [{}]
            if remote_group_id is not None:
                aggregate_addresses_range = \
                    self.secgroup_aggregate_addresses.get(remote_group_id)
                addresses_list = []
                if aggregate_addresses_range is not None:
                    cidr_list = aggregate_addresses_range.iter_cidrs()
                    for aggregate_address in cidr_list:
                        addresses_list.append({
                            ipv4_match_item: SGApp._get_network_and_mask(
                                aggregate_address
                            )
                        })
            elif remote_ip_prefix is not None:
                addresses_list = [{
                    ipv4_match_item: SGApp._get_network_and_mask(
                        remote_ip_prefix
                    )
                }]

            for address_item in addresses_list:
                for match_item in match_list:
                    parameters_merge = match_item.copy()
                    parameters_merge.update(address_item)
                    match = parser.OFPMatch(**parameters_merge)
                    cookie, cookie_mask = self._get_rule_cookie(rule_id)
                    self.mod_flow(
                        cookie=cookie,
                        cookie_mask=cookie_mask,
                        inst=inst,
                        table_id=table_id,
                        priority=priority,
                        match=match)
        elif ethertype == n_const.IPv6:
            # not support yet
            LOG.info(_LI("IPv6 rules are not supported yet"))
        else:
            LOG.error(_LE("wrong ethernet type"))

    def _uninstall_security_group_rule_flows(self, secgroup_rule):
        # uninstall rule flows by its cookie
        ofproto = self.ofproto

        direction = secgroup_rule.get_direction()
        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE

        rule_id = self._get_security_rule_mapping(secgroup_rule.get_id())
        if rule_id is None:
            LOG.error(_LE("the rule_id of the security group rule %s is none"),
                      rule_id)
            return

        cookie, cookie_mask = self._get_rule_cookie(rule_id)
        self.mod_flow(
            cookie=cookie,
            cookie_mask=cookie_mask,
            table_id=table_id,
            command=ofproto.OFPFC_DELETE)

    def _install_env_init_flow_by_direction(self, direction):
        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            goto_table_id = const.INGRESS_DISPATCH_TABLE
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            goto_table_id = const.SERVICES_CLASSIFICATION_TABLE

        parser = self.parser
        ofproto = self.ofproto

        # defaults of sg-table to drop packet
        drop_inst = None
        self.mod_flow(
             inst=drop_inst,
             table_id=table_id,
             priority=const.PRIORITY_DEFAULT)

        # est state, pass
        match = parser.OFPMatch(ct_state=(const.CT_STATE_TRK |
                                          const.CT_STATE_EST,
                                          SG_CT_STATE_MASK))

        goto_inst = [parser.OFPInstructionGotoTable(goto_table_id)]
        self.mod_flow(
             inst=goto_inst,
             table_id=table_id,
             priority=const.PRIORITY_CT_STATE,
             match=match)

        # rel state, pass
        ct_related_not_new_flag = const.CT_STATE_TRK | const.CT_STATE_REL
        ct_related_mask = const.CT_STATE_TRK | const.CT_STATE_REL | \
            const.CT_STATE_NEW | const.CT_STATE_INV
        match = parser.OFPMatch(ct_state=(ct_related_not_new_flag,
                                          ct_related_mask))
        self.mod_flow(
             inst=goto_inst,
             table_id=table_id,
             priority=const.PRIORITY_CT_STATE,
             match=match)

        ct_related_new_flag = const.CT_STATE_TRK | const.CT_STATE_REL | \
            const.CT_STATE_NEW
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ct_state=(ct_related_new_flag,
                                          ct_related_mask))
        actions = [parser.NXActionCT(actions=[],
                                     alg=0,
                                     flags=const.CT_FLAG_COMMIT,
                                     recirc_table=goto_table_id,
                                     zone_ofs_nbits=15,
                                     zone_src=const.CT_ZONE_REG)]
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
             inst=inst,
             table_id=table_id,
             priority=const.PRIORITY_CT_STATE,
             match=match)

        # inv state, drop
        invalid_ct_state_flag = const.CT_STATE_TRK | const.CT_STATE_INV
        match = parser.OFPMatch(ct_state=(invalid_ct_state_flag,
                                          invalid_ct_state_flag))
        self.mod_flow(
             inst=drop_inst,
             table_id=table_id,
             priority=const.PRIORITY_CT_STATE,
             match=match)

    def switch_features_handler(self, ev):
        self._install_env_init_flow_by_direction('ingress')
        self._install_env_init_flow_by_direction('egress')
        self.secgroup_associate_local_ports.clear()
        self.remote_secgroup_ref.clear()
        self.secgroup_aggregate_addresses.clear()
        self.secgroup_ip_refs.clear()

    def _get_security_rule_mapping(self, lrule_id):
        rule_id = self.secgroup_rule_mappings.get(lrule_id)
        if rule_id is not None:
            return rule_id
        else:
            self.next_secgroup_rule_id += 1
            # TODO(ding bo) verify self.next_network_id didn't wrap
            self.secgroup_rule_mappings[lrule_id] = self.next_secgroup_rule_id
            return self.next_secgroup_rule_id

    def _get_secgroup_conj_id_and_priority(self, secgroup_id):
        sg_unique_key = self.db_store.get_unique_key_by_id(
            models.SecurityGroup.table_name, secgroup_id)
        return sg_unique_key, (SG_PRIORITY_OFFSET + sg_unique_key)

    def _associate_secgroup_lport_addresses(self, secgroup_id, lport):
        # update the record of aggregate addresses of ports associated
        # with this security group.
        addresses = self.secgroup_aggregate_addresses[secgroup_id]
        added_ips = self._get_lport_added_ips_for_secgroup(secgroup_id, lport)
        new_cidr_set, added_cidr, removed_cidr = \
            SGApp._get_cidr_changes_after_adding_addresses(
                addresses,
                added_ips,
            )
        self.secgroup_aggregate_addresses[secgroup_id] = new_cidr_set

        # update the flows representing those rules each of which specifies
        #  this security group as its parameter
        # of remote group.
        secrules = self.remote_secgroup_ref.get(secgroup_id)
        if secrules:
            for rule_info in secrules.values():
                self._update_security_group_rule_flows_by_addresses(
                    rule_info.get_security_group_id(),
                    rule_info,
                    added_cidr,
                    removed_cidr)

    def _disassociate_secgroup_lport_addresses(self, secgroup_id, lport):
        # update the record of aggregate addresses of ports associated
        # with this security group.
        aggregate_addresses_range = \
            self.secgroup_aggregate_addresses[secgroup_id]
        if aggregate_addresses_range:
            removed_ips = self._get_lport_removed_ips_for_secgroup(
                secgroup_id, lport)
            new_cidr_set, added_cidr, removed_cidr = \
                SGApp._get_cidr_changes_after_removing_addresses(
                    aggregate_addresses_range,
                    removed_ips,
                )
            if not new_cidr_set:
                del self.secgroup_aggregate_addresses[secgroup_id]
            else:
                self.secgroup_aggregate_addresses[secgroup_id] = new_cidr_set

            # update the flows representing those rules each of which
            # specifies this security group as its
            # parameter of remote group.
            secrules = self.remote_secgroup_ref.get(secgroup_id)
            if secrules:
                for rule_info in secrules.values():
                    self._update_security_group_rule_flows_by_addresses(
                        rule_info.get_security_group_id(),
                        rule_info,
                        added_cidr,
                        removed_cidr
                    )
                    # delete conntrack entities by rule and remote address
                    self._delete_conntrack_entries_by_remote_address(
                        removed_ips, rule_info)

    def _add_local_port_associating(self, lport, secgroup_id):
        self._associate_secgroup_lport_addresses(secgroup_id, lport)

        # update the record of ports associated with this security group.
        associate_ports = \
            self.secgroup_associate_local_ports.get(secgroup_id)
        if associate_ports is None:
            self.secgroup_associate_local_ports[secgroup_id] = \
                [lport.get_id()]
            self._install_security_group_flows(secgroup_id)
        elif lport.get_id() not in associate_ports:
            associate_ports.append(lport.get_id())

        # install associating flow
        self._install_associating_flows(secgroup_id, lport)

    def _remove_local_port_associating(self, lport, secgroup_id):
        # uninstall associating flow
        self._uninstall_associating_flows(secgroup_id, lport)

        self._disassociate_secgroup_lport_addresses(secgroup_id, lport)

        # update the record of ports associated with this security group.
        associate_ports = \
            self.secgroup_associate_local_ports.get(secgroup_id)
        if associate_ports is not None:
            if lport.get_id() in associate_ports:
                associate_ports.remove(lport.get_id())
                # delete conntrack entities by port
                self._delete_conntrack_entries_by_local_port_info(
                    lport, None, secgroup_id)
                if len(associate_ports) == 0:
                    self._uninstall_security_group_flow(secgroup_id)
                    del self.secgroup_associate_local_ports[secgroup_id]

    def _add_remote_port_associating(self, lport, secgroup_id):
        self._associate_secgroup_lport_addresses(secgroup_id, lport)

    def _remove_remote_port_associating(self, lport, secgroup_id):
        self._disassociate_secgroup_lport_addresses(secgroup_id, lport)

    def _update_port_addresses_process(self, lport, original_lport,
                                       secgroup_id):
        """
        Update flows of the security group rules which used this security group
        as remote group because the IP addresses of lport might change.
        """
        # update the record of aggregate addresses of ports associated
        # with this security group.
        aggregate_addresses_range = \
            self.secgroup_aggregate_addresses[secgroup_id]

        added_ips, removed_ips = self._get_lport_updated_ips_for_secgroup(
            secgroup_id, lport, original_lport
        )
        new_cidr_array, added_cidr, removed_cidr = \
            self._get_cidr_changes_after_updating_addresses(
                aggregate_addresses_range,
                added_ips,
                removed_ips
            )
        if len(new_cidr_array) == 0:
            self.secgroup_aggregate_addresses.pop(secgroup_id, None)
        else:
            self.secgroup_aggregate_addresses[secgroup_id] = new_cidr_array

        # update the flows representing those rules each of which
        # specifies this security group as its
        # parameter of remote group.
        secrules = self.remote_secgroup_ref.get(secgroup_id)
        if secrules is not None:
            for rule_info in secrules.values():
                self._update_security_group_rule_flows_by_addresses(
                    rule_info.get_security_group_id(),
                    rule_info,
                    added_cidr,
                    removed_cidr
                )
                # delete conntrack entities by rule and remote address
                self._delete_conntrack_entries_by_remote_address(
                    removed_ips, rule_info)

    def _get_added_and_removed_and_unchanged_secgroups(self, secgroups,
                                                       original_secgroups):
        added_secgroups = []
        unchanged_secgroups = []
        if original_secgroups is not None:
            removed_secgroups = list(original_secgroups)
        else:
            removed_secgroups = []

        if secgroups:
            for item in secgroups:
                if item in removed_secgroups:
                    removed_secgroups.remove(item)
                    unchanged_secgroups.append(item)
                else:
                    added_secgroups.append(item)

        return added_secgroups, removed_secgroups, unchanged_secgroups

    def remove_local_port(self, lport):
        if not netaddr.valid_ipv4(lport.get_ip()):
            LOG.warning(_LW("No support for non IPv4 protocol"))
            return

        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        # uninstall ct table
        self._uninstall_connection_track_flows(lport)

        for secgroup_id in secgroups:
            self._remove_local_port_associating(lport, secgroup_id)

    def remove_remote_port(self, lport):
        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        for secgroup_id in secgroups:
            self._remove_remote_port_associating(lport, secgroup_id)

    def update_local_port(self, lport, original_lport):
        secgroups = lport.get_security_groups()
        original_secgroups = original_lport.get_security_groups()

        added_secgroups, removed_secgroups, unchanged_secgroups = \
            self._get_added_and_removed_and_unchanged_secgroups(
                secgroups, original_secgroups)

        if not secgroups and original_secgroups:
            # uninstall ct table
            self._uninstall_connection_track_flows(lport)

        for secgroup_id in added_secgroups:
            self._add_local_port_associating(lport, secgroup_id)

        for secgroup_id in removed_secgroups:
            self._remove_local_port_associating(original_lport, secgroup_id)

        for secgroup_id in unchanged_secgroups:
            self._update_port_addresses_process(lport, original_lport,
                                                secgroup_id)
            # delete conntrack entities by port addresses changed
            self._delete_conntrack_entries_by_local_port_info(
                lport, original_lport, secgroup_id)

        if secgroups and not original_secgroups:
            # install ct table
            self._install_connection_track_flows(lport)

    def update_remote_port(self, lport, original_lport):
        secgroups = lport.get_security_groups()
        original_secgroups = original_lport.get_security_groups()

        added_secgroups, removed_secgroups, unchanged_secgroups = \
            self._get_added_and_removed_and_unchanged_secgroups(
                secgroups, original_secgroups)

        for secgroup_id in added_secgroups:
            self._add_remote_port_associating(lport, secgroup_id)

        for secgroup_id in removed_secgroups:
            self._remove_remote_port_associating(lport, secgroup_id)

        for secgroup_id in unchanged_secgroups:
            self._update_port_addresses_process(lport, original_lport,
                                                secgroup_id)

    def add_local_port(self, lport):
        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        if not netaddr.valid_ipv4(lport.get_ip()):
            LOG.warning(_LW("No support for non IPv4 protocol"))
            return

        for secgroup_id in secgroups:
            self._add_local_port_associating(lport, secgroup_id)

        # install ct table
        self._install_connection_track_flows(lport)

    def add_remote_port(self, lport):
        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        for secgroup_id in secgroups:
            self._add_remote_port_associating(lport, secgroup_id)

    def _is_sg_not_associated_with_local_port(self, secgroup_id):
        return self.secgroup_associate_local_ports.get(secgroup_id) is None

    def add_security_group_rule(self, secgroup, secgroup_rule):
        secgroup_id = secgroup.get_id()
        if self._is_sg_not_associated_with_local_port(secgroup_id):
            LOG.debug("Security group %s wasn't associated with a local port",
                      secgroup_id)
            return

        LOG.info(_LI("Add a rule %(rule)s to security group %(secgroup)s"),
                 {'rule': secgroup_rule, 'secgroup': secgroup_id})

        # update the record of rules each of which specifies a same security
        #  group as its parameter of remote group.
        remote_group_id = secgroup_rule.get_remote_group_id()
        if remote_group_id is not None:
            associate_rules = self.remote_secgroup_ref.get(remote_group_id)
            if associate_rules is None:
                self.remote_secgroup_ref[remote_group_id] = \
                    {secgroup_rule.get_id(): secgroup_rule}
            else:
                associate_rules[secgroup_rule.get_id()] = secgroup_rule

        self._install_security_group_rule_flows(secgroup_id, secgroup_rule)

    def remove_security_group_rule(self, secgroup, secgroup_rule):
        secgroup_id = secgroup.get_id()
        if self._is_sg_not_associated_with_local_port(secgroup_id):
            LOG.debug("Security group %s wasn't associated with a local port",
                      secgroup_id)
            return

        LOG.info(_LI("Remove a rule %(rule)s to security group %(secgroup)s"),
                 {'rule': secgroup_rule, 'secgroup': secgroup.get_id()})

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(secgroup.get_id())

        # update the record of rules each of which specifies a same security
        # group as its parameter of remote group.
        remote_group_id = secgroup_rule.get_remote_group_id()
        if remote_group_id is not None:
            associate_rules = self.remote_secgroup_ref.get(remote_group_id)
            if associate_rules is not None:
                del associate_rules[secgroup_rule.get_id()]
                if len(associate_rules) == 0:
                    del self.remote_secgroup_ref[remote_group_id]

        self._uninstall_security_group_rule_flows(secgroup_rule)

        # delete conntrack entities by rule
        self._delete_conntrack_entries_by_rule(secgroup_rule)

    def _delete_conntrack_entries_process(self, port_info, rule,
                                          remote_address_list=None):
        ethertype = rule.get_ethertype()
        if 'ingress' == rule.get_direction():
            nw_match_mark = 'nw_dst'
            remote_match_mark = 'nw_src'
        else:
            nw_match_mark = 'nw_src'
            remote_match_mark = 'nw_dst'
        for port_ip in port_info['removed_ips']:
            entries_filter = {
                'ethertype': ethertype,
                nw_match_mark: port_ip,
                'zone': port_info['zone_id']
            }
            protocol = rule.get_protocol()
            if protocol:
                entries_filter['protocol'] = protocol
            if remote_address_list:
                for remote_address in remote_address_list:
                    entries_filter_tmp = entries_filter.copy()
                    entries_filter_tmp[remote_match_mark] = remote_address
                    utils.delete_conntrack_entries_by_filter(
                        **entries_filter_tmp)
            else:
                utils.delete_conntrack_entries_by_filter(**entries_filter)

    def _delete_conntrack_entries_by_rule(self, rule, filter_port_info=None,
                                          filter_remote_addresses=None):
        """Delete connection track entries filtered by a security group rule
        and other filtering parameters.

        :param rule:    a security group rule
        :type rule:     security group rule object
        :param filter_port_info:    local port information
        :type filter_port_info:     a tuple of 'removed_ips' and 'zone_id'
        :param filter_remote_addresses: IP addresses in a lport associated
                                         with the remote group of the rule
        :type filter_remote_addresses:  a list of IP addresses
        """
        if rule.get_ethertype() == n_const.IPv6:
            # Not support IPv6 yet. Because the controller has already printed
            # logs in other methods, there is no need to print extra logs here.
            return

        if filter_remote_addresses:
            remote_address_list = filter_remote_addresses
        else:
            remote_address_list = None
            # Conntrack command only support to delete entries by specifying a
            # net address than a cidr, but the number of addresses transformed
            # from a remote group or a remote ip prefix could be quite huge,
            # DF won't delete conntrack entries filtered by remote group or
            # remote ip prefix.

        if filter_port_info:
            associating_ports_info = [filter_port_info]
        else:
            associating_ports_info = []
            associating_port_ids = self.secgroup_associate_local_ports.get(
                rule.get_security_group_id())
            for port_id in associating_port_ids:
                lport = self.db_store.get_port(port_id)
                removed_ips = self._get_ips_in_logical_port(lport)
                zone_id = lport.get_external_value('local_network_id')
                associating_ports_info.append({'removed_ips': removed_ips,
                                               'zone_id': zone_id})

        for port_info in associating_ports_info:
            self._delete_conntrack_entries_process(
                port_info, rule, remote_address_list)

    def _delete_conntrack_entries_by_local_port_info(
            self, lport, original_lport, secgroup_id):
        """Delete connection track entries filtered by the local lport and the
        associated security group of the lport.
        """
        ips = self._get_ips_in_logical_port(lport)
        if original_lport:
            original_ips = self._get_ips_in_logical_port(original_lport)
            removed_ips = original_ips - ips
        else:
            removed_ips = ips
        zone_id = lport.get_external_value('local_network_id')

        local_port_info = {'removed_ips': removed_ips, 'zone_id': zone_id}
        secgroup = self.db_store.get_security_group(secgroup_id)
        if secgroup is not None:
            for rule in secgroup.get_rules():
                self._delete_conntrack_entries_by_rule(
                    rule, filter_port_info=local_port_info)

    def _delete_conntrack_entries_by_remote_address(self, remote_addresses,
                                                    rule):
        """Delete connection track entries filtered by the security group rule
        and the IP addresses in a lport associated with the remote group of the
        rule.
        """
        self._delete_conntrack_entries_by_rule(
            rule, filter_remote_addresses=remote_addresses)
