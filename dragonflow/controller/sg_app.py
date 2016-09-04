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
from neutron.agent.common import config
from neutron_lib import constants as n_const
from oslo_log import log
from ryu.ofproto import ether

from dragonflow._i18n import _LI, _LE
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app


config.setup_logging()
LOG = log.getLogger(__name__)

SG_CT_STATE_MASK = const.CT_STATE_NEW | const.CT_STATE_EST | \
                   const.CT_STATE_REL | const.CT_STATE_INV | const.CT_STATE_TRK
COOKIE_FULLMASK = 0xffffffffffffffff
SG_PRIORITY_OFFSET = 2


class SGApp(df_base_app.DFlowApp):

    def __init__(self, *args, **kwargs):
        super(SGApp, self).__init__(*args, **kwargs)
        self.secgroup_mappings = {}
        self.secgroup_rule_mappings = {}
        # When the value of a conj_id match is zero, it can match every
        # packets with no conj_id, which is not we expected. So We simply skip
        # the value of zero, and allocate conj_ids begin with one.
        self.next_secgroup_id = 1
        self.next_secgroup_rule_id = 0
        self.secgroup_refcount = {}
        self.remote_secgroup_ref = {}
        self.secgroup_associate_local_ports = {}
        self.secgroup_aggregate_addresses = {}

    @staticmethod
    def _split_range(range_start, range_end, full_mask):
        bit_flag = 1
        last_temp_start = range_start
        last_temp_end = last_temp_start
        result_list = []

        while True:
            if ((last_temp_start & bit_flag) == 0) and \
                    ((last_temp_end | bit_flag) <= range_end):
                last_temp_end |= bit_flag
                bit_flag <<= 1
            else:
                mask = full_mask - (bit_flag - 1)
                result_list.append({"prefix": last_temp_start, "mask": mask})
                if last_temp_end >= range_end:
                    break
                bit_flag = 1
                last_temp_start = last_temp_end + 1
                last_temp_end = last_temp_start

        return result_list

    @staticmethod
    def _try_merge_cidr(current_prefix, current_mask, last_item, full_mask):
        prefix_mask = full_mask & (current_mask << 1)
        bit_check_flag = prefix_mask ^ current_mask
        if (last_item["mask"] == current_mask) and \
                ((last_item["prefix"] & prefix_mask) ==
                 (current_prefix & prefix_mask)) and \
                ((last_item["prefix"] & bit_check_flag) !=
                 (current_prefix & bit_check_flag)):
            return prefix_mask
        return None

    @staticmethod
    def _remove_one_address(cidr_array, address):
        full_mask = 0xffffffff

        added_cidr = []
        removed_cidr = []
        new_cidr_array = cidr_array

        for index in range(len(cidr_array)):
            cidr_item = cidr_array[index]
            temp_min = cidr_item["prefix"]
            temp_max = temp_min + (full_mask - cidr_item["mask"])
            if temp_min <= address <= temp_max:
                removed_cidr.append(cidr_item)
                if temp_min < address:
                    added_cidr.extend(
                        SGApp._split_range(temp_min, address - 1, full_mask)
                    )
                if temp_max > address:
                    added_cidr.extend(
                        SGApp._split_range(address + 1, temp_max, full_mask)
                    )
                new_cidr_array = cidr_array[:index]
                new_cidr_array.extend(added_cidr)
                new_cidr_array.extend(cidr_array[(index + 1):])
                break

        return new_cidr_array, added_cidr, removed_cidr

    @staticmethod
    def _add_one_address(cidr_array, address):
        full_mask = 0xffffffff
        position = None

        for index in range(len(cidr_array)):
            cidr_item = cidr_array[index]
            temp_min = cidr_item["prefix"]
            temp_max = temp_min + (full_mask - cidr_item["mask"])
            if temp_max >= address:
                if temp_min <= address:
                    return cidr_array, [], []
                position = index
                break

        if position is None:
            left_array = list(cidr_array)
            right_array = []
        else:
            left_array = cidr_array[:position]
            right_array = cidr_array[position:]

        added_cidr = []
        removed_cidr = []
        new_cidr_array = []

        current_prefix = address
        current_mask = full_mask
        continue_flag = True
        while continue_flag:
            continue_flag = False

            if len(left_array) != 0:
                left_item = left_array.pop(-1)
                new_mask = SGApp._try_merge_cidr(current_prefix, current_mask,
                                                 left_item, full_mask)
                if new_mask:
                    current_prefix &= new_mask
                    current_mask = new_mask
                    removed_cidr.append(left_item)
                    continue_flag = True
                    continue
                else:
                    left_array.append(left_item)
            if len(right_array) != 0:
                right_item = right_array.pop(0)
                new_mask = SGApp._try_merge_cidr(current_prefix, current_mask,
                                                 right_item, full_mask)
                if new_mask:
                    current_prefix &= new_mask
                    current_mask = new_mask
                    removed_cidr.append(right_item)
                    continue_flag = True
                    continue
                else:
                    right_array.insert(0, right_item)

        added_cidr.append({"prefix": current_prefix, "mask": current_mask})
        new_cidr_array.extend(left_array)
        new_cidr_array.extend(added_cidr)
        new_cidr_array.extend(right_array)

        return new_cidr_array, added_cidr, removed_cidr

    @staticmethod
    def _get_cidr_match(item):
        cidr = ""
        for loop in range(4):
            if loop != 0:
                cidr += "."
            cidr += str(0xff & (item["prefix"] >> (24 - (loop * 8))))

        mask = item["mask"]
        mask_length = 32
        for loop in range(32):
            if (mask & 1) == 0:
                mask_length -= 1
                mask >>= 1
            else:
                break
        cidr += "/" + str(mask_length)

        return cidr

    @staticmethod
    def _get_network_and_mask(cidr):
        result = netaddr.IPNetwork(cidr)
        return result.network, result.netmask

    @staticmethod
    def _get_port_range_match(port_item):
        if port_item["mask"] != 0xffff:
            return port_item["prefix"], port_item["mask"]
        return port_item["prefix"]

    @staticmethod
    def _get_port_match_name(protocol):
        if protocol == 1:
            port_match_name = 'icmpv4_type'
        elif protocol == 6:
            port_match_name = 'tcp_dst'
        elif protocol == 17:
            port_match_name = 'udp_dst'
        else:
            port_match_name = None

        return port_match_name

    @staticmethod
    def _get_integer_value_from_address(address):
        split_list = address.split('.')
        value = 0
        for item in split_list:
            value = (value << 8) + int(item)

        return value

    @staticmethod
    def _get_rule_flows_match_except_net_addresses(secgroup_rule):
        protocol = secgroup_rule.get_protocol()
        port_range_max = secgroup_rule.get_port_range_max()
        port_range_min = secgroup_rule.get_port_range_min()
        ethertype = secgroup_rule.get_ethertype()

        match_list = []
        dl_type_match = {}
        protocol_match = {}
        port_match_list = [{}]
        if ethertype == n_const.IPv4:
            dl_type_match["eth_type"] = ether.ETH_TYPE_IP
            if protocol is not None:
                if protocol == n_const.PROTO_NAME_ICMP:
                    protocol = n_const.PROTO_NUM_ICMP
                elif protocol == n_const.PROTO_NAME_TCP:
                    protocol = n_const.PROTO_NUM_TCP
                elif protocol == n_const.PROTO_NAME_UDP:
                    protocol = n_const.PROTO_NUM_UDP
                else:
                    protocol = int(protocol)

                protocol_match["ip_proto"] = protocol
                port_match_name = SGApp._get_port_match_name(protocol)
                if (port_range_min is not None) and \
                        (port_match_name is not None):
                    port_match_list = []
                    if protocol == 1:
                        icmpv4_match = {port_match_name: int(port_range_min)}
                        if port_range_max is not None:
                            icmpv4_match["icmpv4_code"] = int(port_range_max)
                        port_match_list.append(icmpv4_match)
                    elif (int(port_range_min) == 1 and
                            int(port_range_max) == 65535):
                        port_match_list.append(protocol_match)
                    else:
                        split_port_range = SGApp._split_range(
                            int(port_range_min),
                            int(port_range_max),
                            0xffff
                        )
                        for port_item in split_port_range:
                            port_match_list.append(
                                {port_match_name:
                                 SGApp._get_port_range_match(port_item)}
                            )
        elif ethertype == n_const.IPv6:
            # not support yet
            dl_type_match["eth_type"] = ether.ETH_TYPE_IPV6
        else:
            LOG.error(_LE("wrong Ethernet type"))

        for port_match in port_match_list:
            parameters_merge = dl_type_match.copy()
            parameters_merge.update(protocol_match)
            parameters_merge.update(port_match)
            match_list.append(parameters_merge)

        return match_list

    @staticmethod
    def _get_rule_cookie(rule_id):
        rule_cookie = rule_id << const.SECURITY_GROUP_RULE_COOKIE_SHIFT_LEN
        return rule_cookie & const.SECURITY_GROUP_RULE_COOKIE_MASK

    def _install_security_group_permit_flow_by_direction(self,
                                                         security_group_id,
                                                         direction):
        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            recirc_table = const.INGRESS_DISPATCH_TABLE
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            recirc_table = const.SERVICES_CLASSIFICATION_TABLE

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)
        if conj_id is None:
            LOG.error(_LE("the conj_id of the security group %s is none"),
                      security_group_id)
            return

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, conj_id=conj_id)
        actions = [parser.NXActionCT(actions=[],
                                     alg=0,
                                     flags=const.CT_FLAG_COMMIT,
                                     recirc_table=recirc_table,
                                     zone_ofs_nbits=15,
                                     zone_src=const.CT_ZONE_REG)]
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
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
        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)
        if conj_id is None:
            LOG.error(_LE("the conj_id of the security group %s is none"),
                      security_group_id)
            return

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, conj_id=conj_id)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=table_id,
            match=match,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY)

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
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            tunnel_key = lport.get_tunnel_key()
            lport_classify_match = {"reg7": tunnel_key}
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            ofport = lport.get_external_value('ofport')
            lport_classify_match = {"in_port": ofport}

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)
        if conj_id is None:
            LOG.error(_LE("the conj_id of the security group (%s) is none"),
                      security_group_id)
            return

        match = parser.OFPMatch(ct_state=(const.CT_STATE_TRK |
                                          const.CT_STATE_NEW,
                                          SG_CT_STATE_MASK),
                                **lport_classify_match)
        actions = [parser.NXActionConjunction(clause=0,
                                              n_clauses=2,
                                              id_=conj_id)]
        action_inst = self.get_datapath(). \
            ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)

        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=table_id,
            priority=priority,
            match=match)

    def _uninstall_associating_flow_by_direction(self, security_group_id,
                                                 lport, direction):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            tunnel_key = lport.get_tunnel_key()
            lport_classify_match = {"reg7": tunnel_key}
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            ofport = lport.get_external_value('ofport')
            lport_classify_match = {"in_port": ofport}

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(security_group_id)
        if conj_id is None:
            LOG.error(_LE("the conj_id of the security group %s is none"),
                      security_group_id)
            return

        match = parser.OFPMatch(ct_state=(const.CT_STATE_TRK |
                                          const.CT_STATE_NEW,
                                          SG_CT_STATE_MASK),
                                **lport_classify_match)

        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=table_id,
            priority=priority,
            match=match,
            command=ofproto.OFPFC_DELETE_STRICT,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY)

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
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        if direction == 'ingress':
            pre_table_id = const.INGRESS_CONNTRACK_TABLE
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            tunnel_key = lport.get_tunnel_key()
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
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=pre_table_id,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _uninstall_connection_track_flow_by_direction(self, lport, direction):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        if direction == 'ingress':
            pre_table_id = const.INGRESS_CONNTRACK_TABLE
            tunnel_key = lport.get_tunnel_key()
            lport_classify_match = {"reg7": tunnel_key}
        else:
            pre_table_id = const.EGRESS_CONNTRACK_TABLE
            ofport = lport.get_external_value('ofport')
            lport_classify_match = {"in_port": ofport}

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                **lport_classify_match)

        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=pre_table_id,
            match=match,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY)

    def _install_connection_track_flows(self, lport):
        self._install_connection_track_flow_by_direction(lport, 'ingress')
        self._install_connection_track_flow_by_direction(lport, 'egress')

    def _uninstall_connection_track_flows(self, lport):
        self._uninstall_connection_track_flow_by_direction(lport, 'ingress')
        self._uninstall_connection_track_flow_by_direction(lport, 'egress')

    def _update_security_group_rule_flows_by_addresses(self,
                                                       secgroup,
                                                       secgroup_rule,
                                                       added_cidr,
                                                       removed_cidr):
        conj_id, priority = self._get_secgroup_conj_id_and_priority(secgroup)
        if conj_id is None:
            LOG.error(_LE("the conj_id of the security group (%s) is none"),
                      secgroup)
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        rule_id = self._get_security_rule_mapping(secgroup_rule.get_id())

        match_list = \
            SGApp._get_rule_flows_match_except_net_addresses(secgroup_rule)

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
        action_inst = self.get_datapath(). \
            ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]

        for added_cidr_item in added_cidr:
            for match_item in match_list:
                parameters_merge = match_item.copy()
                parameters_merge[ipv4_match_item] = \
                    SGApp._get_network_and_mask(
                        SGApp._get_cidr_match(added_cidr_item))
                match = parser.OFPMatch(**parameters_merge)
                self.mod_flow(
                    self.get_datapath(),
                    cookie=SGApp._get_rule_cookie(rule_id),
                    cookie_mask=COOKIE_FULLMASK,
                    inst=inst,
                    table_id=table_id,
                    priority=priority,
                    match=match)

        for removed_cidr_item in removed_cidr:
            for match_item in match_list:
                parameters_merge = match_item.copy()
                parameters_merge[ipv4_match_item] = \
                    SGApp._get_network_and_mask(
                        SGApp._get_cidr_match(removed_cidr_item))
                match = parser.OFPMatch(**parameters_merge)
                self.mod_flow(
                    datapath=self.get_datapath(),
                    table_id=table_id,
                    priority=priority,
                    match=match,
                    command=ofproto.OFPFC_DELETE_STRICT,
                    out_port=ofproto.OFPP_ANY,
                    out_group=ofproto.OFPG_ANY)

    def _install_security_group_rule_flows(self, secgroup, secgroup_rule):
        conj_id, priority = self._get_secgroup_conj_id_and_priority(secgroup)
        if conj_id is None:
            LOG.error(_LE("the conj_id of the security group %s is none"),
                      secgroup)
            return

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
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
            SGApp._get_rule_flows_match_except_net_addresses(secgroup_rule)

        actions = [parser.NXActionConjunction(clause=1,
                                              n_clauses=2,
                                              id_=conj_id)]
        action_inst = self.get_datapath(). \
            ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]

        if ethertype == n_const.IPv4:
            addresses_list = [{}]
            if remote_group_id is not None:
                aggregate_addresses_range = \
                    self.secgroup_aggregate_addresses.get(remote_group_id)
                addresses_list = []
                if aggregate_addresses_range is not None:
                    for aggregate_address in aggregate_addresses_range:
                        addresses_list.append({
                            ipv4_match_item: SGApp._get_network_and_mask(
                                SGApp._get_cidr_match(aggregate_address)
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
                    self.mod_flow(
                        self.get_datapath(),
                        cookie=SGApp._get_rule_cookie(rule_id),
                        cookie_mask=COOKIE_FULLMASK,
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
        ofproto = self.get_datapath().ofproto

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

        self.mod_flow(
            datapath=self.get_datapath(),
            cookie=SGApp._get_rule_cookie(rule_id),
            cookie_mask=const.SECURITY_GROUP_RULE_COOKIE_MASK,
            table_id=table_id,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY)

    def _install_env_init_flow_by_direction(self, direction):
        if direction == 'ingress':
            table_id = const.INGRESS_SECURITY_GROUP_TABLE
            goto_table_id = const.INGRESS_DISPATCH_TABLE
        else:
            table_id = const.EGRESS_SECURITY_GROUP_TABLE
            goto_table_id = const.SERVICES_CLASSIFICATION_TABLE

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        # defaults of sg-table to drop packet
        drop_inst = None
        self.mod_flow(
             self.get_datapath(),
             inst=drop_inst,
             table_id=table_id,
             priority=const.PRIORITY_DEFAULT)

        # est state, pass
        match = parser.OFPMatch(ct_state=(const.CT_STATE_TRK |
                                          const.CT_STATE_EST,
                                          SG_CT_STATE_MASK))

        goto_inst = [parser.OFPInstructionGotoTable(goto_table_id)]
        self.mod_flow(
             self.get_datapath(),
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
             self.get_datapath(),
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
        action_inst = self.get_datapath(). \
            ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [action_inst]
        self.mod_flow(
             self.get_datapath(),
             inst=inst,
             table_id=table_id,
             priority=const.PRIORITY_CT_STATE,
             match=match)

        # inv state, drop
        invalid_ct_state_flag = const.CT_STATE_TRK | const.CT_STATE_INV
        match = parser.OFPMatch(ct_state=(invalid_ct_state_flag,
                                          invalid_ct_state_flag))
        self.mod_flow(
             self.get_datapath(),
             inst=drop_inst,
             table_id=table_id,
             priority=const.PRIORITY_CT_STATE,
             match=match)

    def switch_features_handler(self, ev):
        if self.get_datapath() is None:
            return

        self._install_env_init_flow_by_direction('ingress')
        self._install_env_init_flow_by_direction('egress')

    def _get_security_rule_mapping(self, lrule_id):
        rule_id = self.secgroup_rule_mappings.get(lrule_id)
        if rule_id is not None:
            return rule_id
        else:
            self.next_secgroup_rule_id += 1
            # TODO(ding bo) verify self.next_network_id didn't wrap
            self.secgroup_rule_mappings[lrule_id] = self.next_secgroup_rule_id
            return self.next_secgroup_rule_id

    def _allocate_security_group_id(self, lgroup_id):
        # allocate a number
        security_id = self.next_secgroup_id
        LOG.info(_LI("allocate a number %(security_id)s to the security group "
                     "%(lgroup_id)s")
                 % {'security_id': security_id,
                    'lgroup_id': lgroup_id})
        self.next_secgroup_id += 1

        # save in DB
        # TODO(yuanwei)

        # save in local mapping
        self.secgroup_mappings[lgroup_id] = security_id

    def _release_security_group_id(self, lgroup_id):
        # release in local mapping
        security_id = self.secgroup_mappings.get(lgroup_id)
        LOG.info(_LI("release the allocated number %(security_id)s of the"
                     "security group %(lgroup_id)s")
                 % {'security_id': security_id,
                    'lgroup_id': lgroup_id})
        if security_id is not None:
            del self.secgroup_mappings[lgroup_id]

        # release in DB
        # TODO(yuan wei)

        # release this number
        # TODO(yuan wei)

    def _get_secgroup_conj_id_and_priority(self, lgroup_id):
        security_id = self.secgroup_mappings.get(lgroup_id)
        if security_id is not None:
            return security_id, (SG_PRIORITY_OFFSET + security_id)
        return None, None

    def _add_local_port_associating(self, lport, secgroup_id):
        # update the record of aggregate addresses of ports associated
        # with this security group.
        aggregate_addresses_range = \
            self.secgroup_aggregate_addresses.get(secgroup_id)
        if aggregate_addresses_range is None:
            aggregate_addresses_range = []
        new_cidr_array, added_cidr, removed_cidr = SGApp._add_one_address(
            aggregate_addresses_range,
            SGApp._get_integer_value_from_address(lport.get_ip())
        )
        self.secgroup_aggregate_addresses[secgroup_id] = new_cidr_array

        # update the flows representing those rules each of which specifies
        #  this security group as its parameter
        # of remote group.
        secrules = self.remote_secgroup_ref.get(secgroup_id)
        if secrules is not None:
            for rule_info in secrules.values():
                self._update_security_group_rule_flows_by_addresses(
                    rule_info.get_security_group_id(),
                    rule_info,
                    added_cidr,
                    removed_cidr)

        # update the record of ports associated with this security group.
        associate_ports = \
            self.secgroup_associate_local_ports.get(secgroup_id)
        if associate_ports is None:
            self.secgroup_associate_local_ports[secgroup_id] = \
                [lport.get_id()]
            self._allocate_security_group_id(secgroup_id)
            self._install_security_group_flows(secgroup_id)
        elif lport.get_id() not in associate_ports:
            associate_ports.append(lport.get_id())

        # install associating flow
        self._install_associating_flows(secgroup_id, lport)

    def _remove_local_port_associating(self, lport, secgroup_id):
        # uninstall associating flow
        self._uninstall_associating_flows(secgroup_id, lport)

        # update the record of aggregate addresses of ports associated
        # with this security group.
        aggregate_addresses_range = \
            self.secgroup_aggregate_addresses.get(secgroup_id)
        if aggregate_addresses_range is not None:
            new_cidr_array, added_cidr, removed_cidr = \
                SGApp._remove_one_address(
                    aggregate_addresses_range,
                    SGApp._get_integer_value_from_address(lport.get_ip())
                )
            if len(new_cidr_array) == 0:
                del self.secgroup_aggregate_addresses[secgroup_id]
            else:
                self.secgroup_aggregate_addresses[secgroup_id] = \
                    new_cidr_array

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

        # update the record of ports associated with this security group.
        associate_ports = \
            self.secgroup_associate_local_ports.get(secgroup_id)
        if associate_ports is not None:
            if lport.get_id() in associate_ports:
                associate_ports.remove(lport.get_id())
                if len(associate_ports) == 0:
                    self._uninstall_security_group_flow(secgroup_id)
                    self._release_security_group_id(secgroup_id)
                    del self.secgroup_associate_local_ports[secgroup_id]

    def _add_remote_port_associating(self, lport, secgroup_id):
        # update the record of aggregate addresses of ports associated
        # with this security group.
        aggregate_addresses_range = \
            self.secgroup_aggregate_addresses.get(secgroup_id)
        if aggregate_addresses_range is None:
            aggregate_addresses_range = []
        new_cidr_array, added_cidr, removed_cidr =\
            SGApp._add_one_address(
                aggregate_addresses_range,
                SGApp._get_integer_value_from_address(lport.get_ip())
            )
        self.secgroup_aggregate_addresses[secgroup_id] = new_cidr_array

        # update the flows representing those rules each of which specifies
        #  this security group as its parameter of remote group.
        secrules = self.remote_secgroup_ref.get(secgroup_id)
        if secrules is not None:
            for rule_info in secrules.values():
                self._update_security_group_rule_flows_by_addresses(
                    rule_info.get_security_group_id(),
                    rule_info,
                    added_cidr,
                    removed_cidr
                )

    def _remove_remote_port_associating(self, lport, secgroup_id):
        # update the record of aggregate addresses of ports associated
        # with this security group.
        aggregate_addresses_range = \
            self.secgroup_aggregate_addresses.get(secgroup_id)
        if aggregate_addresses_range is not None:
            new_cidr_array, added_cidr, removed_cidr = \
                SGApp._remove_one_address(
                    aggregate_addresses_range,
                    SGApp._get_integer_value_from_address(lport.get_ip())
                )
            if len(new_cidr_array) == 0:
                del self.secgroup_aggregate_addresses[secgroup_id]
            else:
                self.secgroup_aggregate_addresses[secgroup_id] =\
                    new_cidr_array

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

    def _get_added_and_removed_secgroups(self, secgroups, original_secgroups):
        added_secgroups = []
        if original_secgroups is not None:
            removed_secgroups = list(original_secgroups)
        else:
            removed_secgroups = []

        if secgroups:
            for item in secgroups:
                if item in removed_secgroups:
                    removed_secgroups.remove(item)
                else:
                    added_secgroups.append(item)

        return added_secgroups, removed_secgroups

    def remove_local_port(self, lport):
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        # uninstall ct table
        self._uninstall_connection_track_flows(lport)

        for secgroup_id in secgroups:
            self._remove_local_port_associating(lport, secgroup_id)

    def remove_remote_port(self, lport):
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        for secgroup_id in secgroups:
            self._remove_remote_port_associating(lport, secgroup_id)

    def update_local_port(self, lport, original_lport):
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        secgroups = lport.get_security_groups()
        original_secgroups = original_lport.get_security_groups()

        added_secgroups, removed_secgroups = \
            self._get_added_and_removed_secgroups(secgroups,
                                                  original_secgroups)

        if not secgroups and original_secgroups:
            # uninstall ct table
            self._uninstall_connection_track_flows(lport)

        for secgroup_id in added_secgroups:
            self._add_local_port_associating(lport, secgroup_id)

        for secgroup_id in removed_secgroups:
            self._remove_local_port_associating(lport, secgroup_id)

        if secgroups and not original_secgroups:
            # install ct table
            self._install_connection_track_flows(lport)

    def update_remote_port(self, lport, original_lport):
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        secgroups = lport.get_security_groups()
        original_secgroups = original_lport.get_security_groups()

        added_secgroups, removed_secgroups = \
            self._get_added_and_removed_secgroups(secgroups,
                                                  original_secgroups)

        for secgroup_id in added_secgroups:
            self._add_remote_port_associating(lport, secgroup_id)

        for secgroup_id in removed_secgroups:
            self._remove_remote_port_associating(lport, secgroup_id)

    def add_local_port(self, lport):
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        for secgroup_id in secgroups:
            self._add_local_port_associating(lport, secgroup_id)

        # install ct table
        self._install_connection_track_flows(lport)

    def add_remote_port(self, lport):
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        secgroups = lport.get_security_groups()
        if not secgroups:
            return

        for secgroup_id in secgroups:
            self._add_remote_port_associating(lport, secgroup_id)

    def add_security_group_rule(self, secgroup, secgroup_rule):
        LOG.info(_LI("add a rule %(rule)s to security group %(secgroup)s")
                 % {'rule': secgroup_rule, 'secgroup': secgroup.get_id()})
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(secgroup.get_id())
        if conj_id is None:
            # this security group wasn't associated with a local port
            LOG.info(_LI("this security group %s wasn't associated with"
                         " a local port"), secgroup.get_id())
            return

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

        self._install_security_group_rule_flows(
                secgroup.get_id(), secgroup_rule)

    def remove_security_group_rule(self, secgroup, secgroup_rule):
        LOG.info(_LI("remove a rule %(rule)s to security group %(secgroup)s")
                 % {'rule': secgroup_rule, 'secgroup': secgroup.get_id()})
        if self.get_datapath() is None:
            LOG.error(_LE("datapath is none"))
            return

        conj_id, priority = \
            self._get_secgroup_conj_id_and_priority(secgroup.get_id())
        if conj_id is None:
            # this security group wasn't associated with a local port
            LOG.info(_LI("this security group %s wasn't associated with"
                         " a local port"), secgroup.get_id())
            return

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
