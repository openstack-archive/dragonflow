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

from neutron_lib import constants as n_const
from oslo_log import log
from ryu.lib.packet import arp
from ryu.lib.packet import in_proto
from ryu.ofproto import ether

from dragonflow.controller.common import constants as const
from dragonflow.controller.common import utils
from dragonflow.controller import df_base_app
from dragonflow.db.models import l2


LOG = log.getLogger(__name__)
IPV4_SRC_MATCH_ITEM = 'ipv4_src'
IPV6_SRC_MATCH_ITEM = 'ipv6_src'


class PortSecApp(df_base_app.DFlowApp):

    def _add_flow_drop(self, priority, match):
        drop_inst = None
        self.mod_flow(
             inst=drop_inst,
             table_id=const.EGRESS_PORT_SECURITY_TABLE,
             priority=priority,
             match=match)

    def _get_allow_ip_mac_pairs(self, lport):
        allowed_ip_mac_pairs = []

        fixed_ips = lport.ips
        fixed_mac = lport.mac
        if (fixed_ips is not None) and (fixed_mac is not None):
            for fixed_ip in fixed_ips:
                allowed_ip_mac_pairs.append(
                    l2.AddressPair(ip_address=fixed_ip,
                                   mac_address=fixed_mac))

        allow_address_pairs = lport.allowed_address_pairs
        if allow_address_pairs is not None:
            allowed_ip_mac_pairs.extend(allow_address_pairs)

        return allowed_ip_mac_pairs

    def _get_allow_macs(self, lport):
        allowed_macs = set()

        fixed_mac = lport.mac
        if fixed_mac is not None:
            allowed_macs.add(fixed_mac)

        allow_address_pairs = lport.allowed_address_pairs
        allowed_macs.union(allow_address_pair.mac_address
                           for allow_address_pair in allow_address_pairs)

        return allowed_macs

    def _get_ip_address_match_item(self, ip_version):
        """
        Returns the match_item that should be matched in the flow
        :param ip_version: The ethernet type relevant to the flow {IPv4 | IPv6}
        """
        match_items = {
            (n_const.IP_VERSION_4): IPV4_SRC_MATCH_ITEM,
            (n_const.IP_VERSION_6): IPV6_SRC_MATCH_ITEM
        }
        return match_items[ip_version]

    def _get_ip_match_obj(self, unique_key, mac, ip=None):
        parser = self.parser
        match_items = {'reg6': unique_key,
                       'eth_src': mac,
                       'eth_type': ether.ETH_TYPE_IP}
        if ip:
            ip_version = netaddr.IPAddress(ip).version
            ip_match_item = self._get_ip_address_match_item(ip_version)
            match_items[ip_match_item] = ip
            match_items['eth_type'] = utils.get_eth_from_ip_version(ip_version)

        match = parser.OFPMatch(**match_items)
        return match

    def _get_arp_match_obj(self, unique_key, mac, ip=0, arp_op=None):
        parser = self.parser
        match_items = {'reg6': unique_key,
                       'eth_src': mac,
                       'eth_type': ether.ETH_TYPE_ARP,
                       'arp_spa': ip,
                       'arp_sha': mac
                       }
        if arp_op:
            match_items['arp_op'] = arp_op
        match = parser.OFPMatch(**match_items)
        return match

    def _get_nd_match_object(self, unique_key, mac, ip=None):
        parser = self.parser
        matchdict = {
            'reg6': unique_key,
            'eth_src': mac,
            'eth_type': ether.ETH_TYPE_IPV6,
            'ip_proto': in_proto.IPPROTO_ICMPV6
        }
        if ip:
            matchdict['ipv6_src'] = ip
        match = parser.OFPMatch(**matchdict)
        return match

    def _install_flows_check_valid_ip_and_mac(self, unique_key, ip, mac):
        match = self._get_ip_match_obj(unique_key, mac, ip)
        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

        ip_version = netaddr.IPAddress(ip).version
        if (ip_version == n_const.IP_VERSION_4):
            # Valid arp request
            match = self._get_arp_match_obj(unique_key, mac, ip)
        else:
            match = self._get_nd_match_object(unique_key, mac, ip)
        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  match=match)

    def _uninstall_flows_check_valid_ip_and_mac(self, unique_key, ip, mac):
        # Remove valid ip mac pair pass
        match = self._get_ip_match_obj(unique_key, mac, ip)
        self._remove_one_port_security_flow(const.PRIORITY_HIGH, match)

        ip_version = netaddr.IPAddress(ip).version
        if (ip_version == n_const.IP_VERSION_4):
            # Remove valid arp request
            match = self._get_arp_match_obj(unique_key, mac, ip)
        else:
            match = self._get_nd_match_object(unique_key, mac, ip)
        self._remove_one_port_security_flow(const.PRIORITY_HIGH, match)

    def _install_flows_check_valid_mac(self, unique_key, mac):
        parser = self.parser

        # Other packets with valid source mac pass
        match = parser.OFPMatch(reg6=unique_key,
                                eth_src=mac)
        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_LOW,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  match=match)

    def _uninstall_flows_check_valid_mac(self, unique_key, mac):
        parser = self.parser

        # Remove other packets with valid source mac pass
        match = parser.OFPMatch(reg6=unique_key,
                                eth_src=mac)
        self._remove_one_port_security_flow(const.PRIORITY_LOW, match)

    def _install_flows_check_only_vm_mac(self, unique_key, vm_mac):
        parser = self.parser

        # DHCP packets with the vm mac pass
        match = parser.OFPMatch(reg6=unique_key,
                                eth_src=vm_mac,
                                eth_dst=const.BROADCAST_MAC,
                                eth_type=ether.ETH_TYPE_IP,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCP_CLIENT_PORT,
                                udp_dst=const.DHCP_SERVER_PORT)

        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

        # DHCPv6 packets with the vm mac pass
        match = parser.OFPMatch(reg6=unique_key,
                                eth_src=vm_mac,
                                eth_dst=const.BROADCAST_MAC,
                                eth_type=ether.ETH_TYPE_IPV6,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCPV6_CLIENT_PORT,
                                udp_dst=const.DHCPV6_SERVER_PORT)

        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

        # Arp probe packets with the vm mac pass
        match = self._get_arp_match_obj(unique_key=unique_key,
                                        mac=vm_mac,
                                        arp_op=arp.ARP_REQUEST)
        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  match=match)

        match = self._get_nd_match_object(unique_key, vm_mac)
        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  match=match)

    def _uninstall_flows_check_only_vm_mac(self, unique_key, vm_mac):
        parser = self.parser

        # Remove DHCP packets with the vm mac pass
        match = parser.OFPMatch(reg6=unique_key,
                                eth_src=vm_mac,
                                eth_dst=const.BROADCAST_MAC,
                                eth_type=ether.ETH_TYPE_IP,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCP_CLIENT_PORT,
                                udp_dst=const.DHCP_SERVER_PORT)
        self._remove_one_port_security_flow(const.PRIORITY_HIGH, match)

        # Remove DHCPv6 packets with the vm mac pass
        match = parser.OFPMatch(reg6=unique_key,
                                eth_src=vm_mac,
                                eth_dst=const.BROADCAST_MAC,
                                eth_type=ether.ETH_TYPE_IPV6,
                                ip_proto=n_const.PROTO_NUM_UDP,
                                udp_src=const.DHCP_CLIENT_PORT,
                                udp_dst=const.DHCP_SERVER_PORT)
        self._remove_one_port_security_flow(const.PRIORITY_HIGH, match)

        # Remove arp probe packets with the vm mac pass
        match = self._get_arp_match_obj(unique_key=unique_key,
                                        mac=vm_mac,
                                        arp_op=arp.ARP_REQUEST)
        self._remove_one_port_security_flow(const.PRIORITY_HIGH, match)

        # Remove arp probe packets with the vm mac pass
        match = self._get_nd_match_object(unique_key, vm_mac)
        self._remove_one_port_security_flow(const.PRIORITY_HIGH, match)

    def _install_port_security_flows(self, lport):
        unique_key = lport.unique_key

        # install ip and mac check flows
        allowed_ip_mac_pairs = self._get_allow_ip_mac_pairs(lport)
        for ip_mac_pair in allowed_ip_mac_pairs:
            self._install_flows_check_valid_ip_and_mac(
                unique_key, ip_mac_pair.ip_address,
                ip_mac_pair.mac_address
            )

        # install vm mac and allowed address pairs mac check flows
        allowed_macs = self._get_allow_macs(lport)
        for allowed_mac in allowed_macs:
            self._install_flows_check_valid_mac(unique_key, allowed_mac)

        # install only vm mac check flows
        vm_mac = lport.mac
        self._install_flows_check_only_vm_mac(unique_key, vm_mac)

    def _update_port_security_flows(self, lport, original_lport):
        unique_key = lport.unique_key

        # update ip and mac check flows
        added_ip_mac_pairs, removed_ip_mac_pairs = \
            self._get_added_and_removed_ip_mac_pairs(lport,
                                                     original_lport)
        for item in added_ip_mac_pairs:
            self._install_flows_check_valid_ip_and_mac(
                unique_key, item.ip_address, item.mac_address)
        for item in removed_ip_mac_pairs:
            self._uninstall_flows_check_valid_ip_and_mac(
                unique_key, item.ip_address, item.mac_address)

        # update vm mac and allowed address pairs mac check flows
        added_valid_macs, removed_valid_macs = \
            self._get_added_and_removed_valid_macs(lport,
                                                   original_lport)
        for item in added_valid_macs:
            self._install_flows_check_valid_mac(unique_key, item)
        for item in removed_valid_macs:
            self._uninstall_flows_check_valid_mac(unique_key, item)

        # update only vm mac check flows
        new_vm_mac = lport.mac
        old_vm_mac = original_lport.mac
        if new_vm_mac != old_vm_mac:
            self._install_flows_check_only_vm_mac(unique_key, new_vm_mac)
            self._uninstall_flows_check_only_vm_mac(unique_key, old_vm_mac)

    def _remove_one_port_security_flow(self, priority, match):
        ofproto = self.ofproto
        self.mod_flow(table_id=const.EGRESS_PORT_SECURITY_TABLE,
                      priority=priority,
                      match=match,
                      command=ofproto.OFPFC_DELETE_STRICT)

    def _uninstall_port_security_flows(self, lport):
        unique_key = lport.unique_key

        # uninstall ip and mac check flows
        allowed_ip_mac_pairs = self._get_allow_ip_mac_pairs(lport)
        for ip_mac_pair in allowed_ip_mac_pairs:
            self._uninstall_flows_check_valid_ip_and_mac(
                unique_key,
                ip_mac_pair.ip_address,
                ip_mac_pair.mac_address
            )

        # uninstall vm mac and allowed address pairs mac check flows
        allowed_macs = self._get_allow_macs(lport)
        for allowed_mac in allowed_macs:
            self._uninstall_flows_check_valid_mac(unique_key, allowed_mac)

        # uninstall only vm mac check flows
        vm_mac = lport.mac
        self._uninstall_flows_check_only_vm_mac(unique_key, vm_mac)

    def _install_disable_flow(self, lport):

        unique_key = lport.unique_key
        parser = self.parser

        # Send packets to next table directly
        match = parser.OFPMatch(reg6=unique_key)
        self.add_flow_go_to_table(const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

    def _uninstall_disable_flow(self, lport):

        unique_key = lport.unique_key
        parser = self.parser

        # Remove send packets to next table directly
        match = parser.OFPMatch(reg6=unique_key)
        self._remove_one_port_security_flow(const.PRIORITY_HIGH, match)

    def _subtract_lists(self, list1, list2):
        list1_subtract_list2 = [item for item in list1 if item not in list2]
        list2_subtract_list1 = [item for item in list2 if item not in list1]

        return list1_subtract_list2, list2_subtract_list1

    def _get_added_and_removed_ip_mac_pairs(self, lport, original_lport):
        new_pairs = self._get_allow_ip_mac_pairs(lport)
        old_pairs = self._get_allow_ip_mac_pairs(original_lport)

        added_pairs, removed_pairs = self._subtract_lists(new_pairs, old_pairs)
        return added_pairs, removed_pairs

    def _get_added_and_removed_valid_macs(self, lport, original_lport):
        new_valid_macs = self._get_allow_macs(lport)
        old_valid_macs = self._get_allow_macs(original_lport)

        added_valid_macs, removed_valid_macs = \
            self._subtract_lists(new_valid_macs, old_valid_macs)
        return added_valid_macs, removed_valid_macs

    def switch_features_handler(self, ev):
        parser = self.parser

        # Ip default drop
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self._add_flow_drop(const.PRIORITY_MEDIUM, match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6)
        self._add_flow_drop(const.PRIORITY_MEDIUM, match)

        # Arp default drop
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP)
        self._add_flow_drop(const.PRIORITY_MEDIUM, match)

        # Default drop
        self._add_flow_drop(const.PRIORITY_VERY_LOW, None)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _add_local_port(self, lport):
        enable = lport.port_security_enabled
        if enable:
            self._install_port_security_flows(lport)
        else:
            self._install_disable_flow(lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_LOCAL_UPDATED)
    def _update_local_port(self, lport, original_lport):
        enable = lport.port_security_enabled
        original_enable = original_lport.port_security_enabled

        if enable:
            if original_enable:
                self._update_port_security_flows(lport, original_lport)

            else:
                self._install_port_security_flows(lport)
                self._uninstall_disable_flow(original_lport)
        else:
            if original_enable:
                self._install_disable_flow(lport)
                self._uninstall_port_security_flows(original_lport)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _remove_local_port(self, lport):
        enable = lport.port_security_enabled
        if enable:
            self._uninstall_port_security_flows(lport)
        else:
            self._uninstall_disable_flow(lport)
