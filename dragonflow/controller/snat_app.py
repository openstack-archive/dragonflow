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
from oslo_config import cfg
from oslo_log import log
from ryu.ofproto import ether

from dragonflow.controller import base_snat_app
from dragonflow.controller.common import constants as const

LOG = log.getLogger(__name__)


class SNATApp(base_snat_app.BaseSNATApp):
    """Implements single global IP allocation strategy for all hosted VMs

    Methods provide strategy specific operations
    Application has extra parameters
    - external_host_ip - should be defined in provider range
    -external_host_mac - optional
    """
    def __init__(self, *args, **kwargs):
        super(SNATApp, self).__init__(*args, **kwargs)
        # new application configuration
        self.external_host_ip = cfg.CONF.df_snat_app.external_host_ip
        self.external_host_mac = cfg.CONF.df_snat_app.external_host_mac

    def ovs_port_updated_helper(self):
        # set correct mac address on update
        if self.count > 0:
            parser = self.parser
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
            self._install_snat_egress_after_conntrack(match,
                                                  self.external_host_mac)

    def install_common_flows(self):
        self._install_ingress_goto_rules()
        self._install_snat_ingress_conntrack()
        self._install_egress_goto_rules()

        parser = self.parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self._install_snat_egress_conntrack(match, self.external_host_ip)
        self._install_snat_egress_after_conntrack(match,
                                                  self.external_host_mac)

        self._install_arp_responder(self.external_host_ip,
                                    self.external_host_mac)

    def install_lport_specific_flows(self, lport):
        # instance specific flows
        self._install_snat_ingress_after_conntrack(
                                        lport.get_ip(),
                                        lport.get_mac(),
                                        self.external_host_mac)

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

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        self._remove_arp_responder(self.external_host_ip,
                                   self.external_host_mac)

    def remove_lport_specific_flows(self, lport):

        vm_ip = lport.get_ip()
        parser = self.parser
        ofproto = self.ofproto
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ct_mark=int(netaddr.IPAddress(vm_ip)))

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_NAT2_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)
