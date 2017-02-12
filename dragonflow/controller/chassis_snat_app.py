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
from oslo_log import log
from ryu.ofproto import ether

from dragonflow import conf as cfg
from dragonflow.controller import base_snat_app
from dragonflow.controller.common import constants as const

LOG = log.getLogger(__name__)

CHASSIS_MAC = '91:92:93:94:95:96'


class ChassisSNATApp(base_snat_app.BaseSNATApp):
    """Implements single global IP allocation strategy for all hosted VMs

    Methods provide strategy specific operations
    Application has extra parameters
    - external_host_ip - should be defined in provider range
    -external_host_mac - optional
    """
    def __init__(self, *args, **kwargs):
        super(ChassisSNATApp, self).__init__(*args, **kwargs)
        # new application configuration
        self.external_host_ip = cfg.CONF.df_snat_app.external_host_ip
        self.external_host_mac = cfg.CONF.df_snat_app.external_host_mac

        if self.external_host_mac is None:
            self.external_host_mac = CHASSIS_MAC

        if self.external_host_ip is None:
            raise Exception(_('External host IP is not set'))

    def ovs_port_updated_helper(self):
        # set correct mac address on update
        if self.count > 0:
            parser = self.parser
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
            self._install_snat_egress_after_conntrack(
                match,
                self.external_host_mac)

    def install_strategy_based_flows(self):
        super(ChassisSNATApp, self).install_strategy_based_flows()

        parser = self.parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self._install_snat_egress_conntrack(match, self.external_host_ip)
        self._install_snat_egress_after_conntrack(
            match,
            self.external_host_mac)

        self._install_arp_responder(
            self.external_host_ip,
            self.external_host_mac)

    def install_lport_based_flows(self, lport):
        # instance specific flows
        self._install_snat_ingress_after_conntrack(
                                        lport.get_unique_key(),
                                        lport.get_mac(),
                                        self.external_host_mac)

    def remove_strategy_based_flows(self):
        super(ChassisSNATApp, self).remove_strategy_based_flows()

        parser = self.parser
        ofproto = self.ofproto

        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_NAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.EGRESS_SNAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

        self._remove_arp_responder(self.external_host_ip,
                                   self.external_host_mac)

    def remove_lport_based_flows(self, lport):
        parser = self.parser
        ofproto = self.ofproto
        unique_key = lport.get_unique_key()
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ct_mark=int(unique_key))

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_SNAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)
