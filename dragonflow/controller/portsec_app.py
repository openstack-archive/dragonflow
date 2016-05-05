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

from neutron.agent.common import config

from ryu.ofproto import ether

from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp

from oslo_log import log
from ryu.lib.mac import haddr_to_bin

config.setup_logging()
LOG = log.getLogger(__name__)


class PortSecApp(DFlowApp):

    def __init__(self, *args, **kwargs):
        super(PortSecApp, self).__init__(*args, **kwargs)

    def _add_flow_drop(self, priority, match):
        drop_inst = None
        self.mod_flow(
             self.get_datapath(),
             inst=drop_inst,
             table_id=const.EGRESS_PORT_SECURITY_TABLE,
             priority=priority,
             match=match)

    def _get_allow_ip_mac_pairs(self, lport):
        allowed_ip_mac_pairs = []

        fixed_ips = lport.get_ip_list()
        fixed_mac = lport.get_mac()
        if (fixed_ips is not None) and (fixed_mac is not None):
            for fixed_ip in fixed_ips:
                allowed_ip_mac_pairs.append(
                    {'ip_address': fixed_ip,
                     'mac_address': fixed_mac})

        allow_address_pairs = lport.get_allow_address_pairs()
        if allow_address_pairs is not None:
            allowed_ip_mac_pairs.extend(allow_address_pairs)

        return allowed_ip_mac_pairs

    def _get_allow_macs(self, lport):
        allowed_macs = set()

        fixed_mac = lport.get_mac()
        if fixed_mac is not None:
            allowed_macs.add(fixed_mac)

        allow_address_pairs = lport.get_allow_address_pairs()
        if allow_address_pairs is not None:
            for allow_address_pair in allow_address_pairs:
                allowed_macs.add(allow_address_pair['mac_address'])

        return allowed_macs

    def _install_flows_check_valid_ip_and_mac(self, datapath, ofport, ip, mac):
        parser = datapath.ofproto_parser

        # Valid ip mac pair pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=mac,
                                eth_type=ether.ETH_TYPE_IP,
                                ipv4_src=ip)
        self.add_flow_go_to_table(datapath,
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

        # Valid arp request/reply pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=mac,
                                eth_type=ether.ETH_TYPE_ARP,
                                arp_spa=ip,
                                arp_sha=mac)
        self.add_flow_go_to_table(datapath,
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  match=match)

    def _uninstall_flows_check_valid_ip_and_mac(self, datapath, ofport,
                                                ip, mac):
        parser = datapath.ofproto_parser

        # Remove valid ip mac pair pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=mac,
                                eth_type=ether.ETH_TYPE_IP,
                                ipv4_src=ip)
        self._remove_one_port_security_flow(datapath, match)

        # Remove valid arp request/reply pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=mac,
                                eth_type=ether.ETH_TYPE_ARP,
                                arp_spa=ip,
                                arp_sha=mac)
        self._remove_one_port_security_flow(datapath, match)

    def _install_flows_check_valid_mac(self, datapath, ofport, mac):
        parser = datapath.ofproto_parser

        # Multicast packets with valid source mac pass
        match = parser.OFPMatch(
            in_port=ofport,
            eth_src=mac,
            eth_type=ether.ETH_TYPE_IP
        )
        eth_dst = haddr_to_bin('01:00:5E:00:00:00')
        eth_dst_mask = haddr_to_bin('FF:FF:FF:80:00:00')
        match.set_dl_dst_masked(eth_dst, eth_dst_mask)
        self.add_flow_go_to_table(datapath,
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

        # Other packets with valid source mac pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=mac)
        self.add_flow_go_to_table(datapath,
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_LOW,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

    def _uninstall_flows_check_valid_mac(self, datapath, ofport, mac):
        parser = datapath.ofproto_parser

        # Remove multicast packets with valid source mac pass
        match = parser.OFPMatch(
            in_port=ofport,
            eth_src=mac,
            eth_type=ether.ETH_TYPE_IP
        )
        eth_dst = haddr_to_bin('01:00:5E:00:00:00')
        eth_dst_mask = haddr_to_bin('FF:FF:FF:80:00:00')
        match.set_dl_dst_masked(eth_dst, eth_dst_mask)
        self._remove_one_port_security_flow(datapath, match)

        # Remove other packets with valid source mac pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=mac)
        self._remove_one_port_security_flow(datapath, match)

    def _install_flows_check_only_vm_mac(self, datapath, ofport, vm_mac):
        parser = datapath.ofproto_parser

        # DHCP packets with the vm mac pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=vm_mac,
                                eth_dst="ff:ff:ff:ff:ff:ff",
                                eth_type=ether.ETH_TYPE_IP,
                                ip_proto=17,
                                udp_src=68,
                                udp_dst=67)
        self.add_flow_go_to_table(datapath,
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

        # Arp probe packets with the vm mac pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=vm_mac,
                                eth_type=ether.ETH_TYPE_ARP,
                                ip_proto=1,
                                arp_spa=0,
                                arp_sha=vm_mac)
        self.add_flow_go_to_table(datapath,
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.SERVICES_CLASSIFICATION_TABLE,
                                  match=match)

    def _uninstall_flows_check_only_vm_mac(self, datapath, ofport, vm_mac):
        parser = datapath.ofproto_parser

        # Remove DHCP packets with the vm mac pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=vm_mac,
                                eth_dst="ff:ff:ff:ff:ff:ff",
                                eth_type=ether.ETH_TYPE_IP,
                                ip_proto=17,
                                udp_src=68,
                                udp_dst=67)
        self._remove_one_port_security_flow(datapath, match)

        # Remove arp probe packets with the vm mac pass
        match = parser.OFPMatch(in_port=ofport,
                                eth_src=vm_mac,
                                eth_type=ether.ETH_TYPE_ARP,
                                ip_proto=1,
                                arp_spa=0,
                                arp_sha=vm_mac)
        self._remove_one_port_security_flow(datapath, match)

    def _install_port_security_flows(self, lport, datapath):
        ofport = lport.get_external_value('ofport')

        # install ip and mac check flows
        allowed_ip_mac_pairs = self._get_allow_ip_mac_pairs(lport)
        for ip_mac_pair in allowed_ip_mac_pairs:
            self._install_flows_check_valid_ip_and_mac(
                datapath, ofport, ip_mac_pair['ip_address'],
                ip_mac_pair['mac_address']
            )

        # install vm mac and allowed address pairs mac check flows
        allowed_macs = self._get_allow_macs(lport)
        for allowed_mac in allowed_macs:
            self._install_flows_check_valid_mac(
                datapath, ofport, allowed_mac
            )

        # install only vm mac check flows
        vm_mac = lport.get_mac()
        self._install_flows_check_only_vm_mac(datapath, ofport, vm_mac)

    def _update_port_security_flows(self, lport, original_lport, datapath):
        ofport = lport.get_external_value('ofport')

        # update ip and mac check flows
        added_ip_mac_pairs, removed_ip_mac_pairs = \
            self._get_added_and_removed_ip_mac_pairs(lport,
                                                     original_lport)
        for item in added_ip_mac_pairs:
            self._install_flows_check_valid_ip_and_mac(
                datapath, ofport, item['ip_address'],
                item['mac_address'])
        for item in removed_ip_mac_pairs:
            self._uninstall_flows_check_valid_ip_and_mac(
                datapath, ofport, item['ip_address'],
                item['mac_address'])

        # update vm mac and allowed address pairs mac check flows
        added_valid_macs, removed_valid_macs = \
            self._get_added_and_removed_valid_macs(lport,
                                                   original_lport)
        for item in added_valid_macs:
            self._install_flows_check_valid_mac(
                datapath, ofport, item)
        for item in removed_valid_macs:
            self._uninstall_flows_check_valid_mac(
                datapath, ofport, item)

        # update only vm mac check flows
        new_vm_mac = lport.get_mac()
        old_vm_mac = original_lport.get_mac()
        if new_vm_mac != old_vm_mac:
            self._install_flows_check_only_vm_mac(datapath, ofport,
                                                  new_vm_mac)
            self._install_flows_check_only_vm_mac(datapath, ofport,
                                                  old_vm_mac)

    def _remove_one_port_security_flow(self, datapath, match):
        ofproto = datapath.ofproto
        self.mod_flow(datapath=datapath,
                      table_id=const.EGRESS_PORT_SECURITY_TABLE,
                      match=match,
                      command=ofproto.OFPFC_DELETE,
                      out_port=ofproto.OFPP_ANY,
                      out_group=ofproto.OFPG_ANY)

    def _uninstall_port_security_flows(self, lport, datapath):
        ofport = lport.get_external_value('ofport')

        # uninstall ip and mac check flows
        allowed_ip_mac_pairs = self._get_allow_ip_mac_pairs(lport)
        for ip_mac_pair in allowed_ip_mac_pairs:
            self._uninstall_flows_check_valid_ip_and_mac(
                datapath, ofport, ip_mac_pair['ip_address'],
                ip_mac_pair['mac_address']
            )

        # uninstall vm mac and allowed address pairs mac check flows
        allowed_macs = self._get_allow_macs(lport)
        for allowed_mac in allowed_macs:
            self._uninstall_flows_check_valid_mac(
                datapath, ofport, allowed_mac
            )

        # uninstall only vm mac check flows
        vm_mac = lport.get_mac()
        self._uninstall_flows_check_only_vm_mac(datapath, ofport, vm_mac)

    def _install_disable_flow(self, lport, datapath):

        ofport = lport.get_external_value('ofport')
        parser = datapath.ofproto_parser

        # Send packets to next table directly
        match = parser.OFPMatch(in_port=ofport)
        self.add_flow_go_to_table(datapath,
                                  const.EGRESS_PORT_SECURITY_TABLE,
                                  const.PRIORITY_HIGH,
                                  const.EGRESS_CONNTRACK_TABLE,
                                  match=match)

    def _uninstall_disable_flow(self, lport, datapath):

        ofport = lport.get_external_value('ofport')
        parser = datapath.ofproto_parser

        # Remove send packets to next table directly
        match = parser.OFPMatch(in_port=ofport)
        self._remove_one_port_security_flow(datapath, match)

    def _get_added_and_removed_ip_mac_pairs(self, lport, original_lport):
        added_pairs = []
        removed_pairs = []

        new_pairs = self._get_allow_ip_mac_pairs(lport)
        old_pairs = self._get_allow_ip_mac_pairs(original_lport)

        for new_pair in new_pairs:
            if new_pair not in old_pairs:
                added_pairs.append(new_pair)

        for old_pair in old_pairs:
            if old_pair not in new_pairs:
                removed_pairs.append(old_pair)

        return added_pairs, removed_pairs

    def _get_added_and_removed_valid_macs(self, lport, original_lport):
        added_valid_macs = []
        removed_valid_macs = []

        new_valid_macs = self._get_allow_macs(lport)
        old_valid_macs = self._get_allow_macs(original_lport)

        for new_valid_mac in new_valid_macs:
            if new_valid_mac not in old_valid_macs:
                added_valid_macs.append(new_valid_mac)

        for old_valid_mac in old_valid_macs:
            if old_valid_mac not in new_valid_macs:
                removed_valid_macs.append(old_valid_mac)

        return added_valid_macs, removed_valid_macs

    def switch_features_handler(self, ev):
        datapath = self.get_datapath()
        if datapath is None:
            return

        parser = datapath.ofproto_parser

        # Ip default drop
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self._add_flow_drop(const.PRIORITY_MEDIUM, match)

        # Arp default drop
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP)
        self._add_flow_drop(const.PRIORITY_MEDIUM, match)

        # Default drop
        self._add_flow_drop(const.PRIORITY_DEFAULT, None)

    def add_local_port(self, lport):
        datapath = self.get_datapath()
        if datapath is None:
            return

        enable = lport.get_port_security_enable()
        if enable:
            self._install_port_security_flows(lport, datapath)
        else:
            self._install_disable_flow(lport, datapath)

    def update_local_port(self, lport, original_lport):
        datapath = self.get_datapath()
        if datapath is None:
            return

        enable = lport.get_port_security_enable()
        original_enable = original_lport.get_port_security_enable()

        if enable:
            if original_enable:
                self._update_port_security_flows(lport, original_lport,
                                                 datapath)

            else:
                self._install_port_security_flows(lport, datapath)
        else:
            if original_enable:
                self._uninstall_port_security_flows(original_lport, datapath)

    def remove_local_port(self, lport):
        datapath = self.get_datapath()
        if datapath is None:
            return

        enable = lport.get_port_security_enable()
        if enable:
            self._uninstall_port_security_flows(lport, datapath)
        else:
            self._uninstall_disable_flow(lport, datapath)
