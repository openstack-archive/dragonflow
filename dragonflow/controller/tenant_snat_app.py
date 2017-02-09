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
import netaddr
from oslo_log import log
from ryu.ofproto import ether

from dragonflow.controller import base_snat_app
from dragonflow.controller.common import constants as const

LOG = log.getLogger(__name__)

EXTERNAL_HOST_IP = 'external_host_ip'
EXTERNAL_HOST_MAC = 'external_host_mac'


class TenantSNATApp(base_snat_app.BaseSNATApp):
    """Implements tenant based IP allocation strategy for all hosted VMs

    Methods provide strategy specific operations

    """
    def __init__(self, *args, **kwargs):
        super(TenantSNATApp, self).__init__(*args, **kwargs)
        self.tenant_info = {}

    def ovs_port_updated_helper(self):
        ports = self.db_store.get_ports_by_chassis(self.chassis)
        parser = self.parser
        for lport in ports:
            if self.is_data_port(lport):
                match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                        eth_src=lport.get_mac())
                self._install_snat_egress_after_conntrack(match,
                    lport.get_binding_profile()[EXTERNAL_HOST_MAC])

    def install_common_flows(self):
        self._install_ingress_goto_rules()
        self._install_snat_ingress_conntrack()
        self._install_egress_goto_rules()

    def install_lport_specific_flows(self, lport):
        # instance specific flows
        ext_host_ip = lport.get_binding_profile()[EXTERNAL_HOST_IP]
        ext_host_mac = lport.get_binding_profile()[EXTERNAL_HOST_MAC]

        self._install_snat_ingress_after_conntrack(
                                        lport.get_ip(),
                                        lport.get_mac(),
                                        ext_host_mac)

        parser = self.parser
        match = parser.OFPMatch(
                eth_type=ether.ETH_TYPE_IP,
                ipv4_src=lport.get_ip())
        self._install_snat_egress_conntrack(match, ext_host_ip)

        match = parser.OFPMatch(
                eth_type=ether.ETH_TYPE_IP,
                eth_src=lport.get_mac())
        self._install_snat_egress_after_conntrack(match, ext_host_mac)

        # update arp responder if required
        tenant_id = lport.get_topic()
        if tenant_id in self.tenant_info:
            self.tenant_info[tenant_id] += 1
        else:
            self.tenant_info[tenant_id] = 1
            self._install_arp_responder(ext_host_ip, ext_host_mac)

    def remove_common_flows(self):
        parser = self.parser
        ofproto = self.ofproto

        match = parser.OFPMatch(in_port=self.external_ofport)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_DEFAULT,
            match=match)

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM_LOW,
            match=match)

    def remove_lport_specific_flows(self, lport):
        parser = self.parser
        ofproto = self.ofproto

        match = parser.OFPMatch(
                eth_type=ether.ETH_TYPE_IP,
                ct_mark=int(netaddr.IPAddress(lport.get_ip())))
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        match = parser.OFPMatch(
                eth_type=ether.ETH_TYPE_IP,
                ipv4_src=lport.get_ip())
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        match = parser.OFPMatch(
                eth_type=ether.ETH_TYPE_IP,
                eth_src=lport.get_mac())
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        # remove arp responder on last tenant instance
        tenant_id = lport.get_topic()
        self.tenant_info[tenant_id] -= 1
        if self.tenant_info[tenant_id] == 0:
            self._remove_arp_responder(
                lport.get_binding_profile()[EXTERNAL_HOST_IP],
                lport.get_binding_profile()[EXTERNAL_HOST_MAC])

            self.tenant_info.pop(tenant_id, None)
