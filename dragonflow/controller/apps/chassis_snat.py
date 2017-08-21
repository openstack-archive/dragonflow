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

from dragonflow._i18n import _
from dragonflow import conf as cfg
from dragonflow.controller.apps import snat_mixin
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_const
from dragonflow.db.models import l2
from dragonflow.db.models import ovs

LOG = log.getLogger(__name__)


class ChassisSNATApp(df_base_app.DFlowApp, snat_mixin.SNATApp_mixin):
    """Implements single global IP allocation strategy for all hosted VMs

    Methods provide strategy specific operations
    Application has extra parameters
    - external_host_ip - should be defined in provider range
    -external_host_mac - optional
    """
    def __init__(self, *args, **kwargs):
        super(ChassisSNATApp, self).__init__(*args, **kwargs)
        LOG.info("Loading SNAT application ... ")
        self.external_network_bridge = (
            cfg.CONF.df_snat_app.external_network_bridge)
        self.external_bridge_mac = self.vswitch_api.get_port_mac_in_use(
                self.external_network_bridge) or const.EMPTY_MAC
        self.chassis = None

        # new application configuration
        self.external_host_ip = cfg.CONF.df.external_host_ip
        self.enable_goto_flows = cfg.CONF.df_snat_app.enable_goto_flows

        # create mac address based on given 'external_host_ip'
        if self.external_host_ip is not None:
            split_ip = self.external_host_ip.split('.')
            ip2mac = '{:02x}:{:02x}:{:02x}:{:02x}'.format(*map(int, split_ip))
            self.external_host_mac = const.CHASSIS_MAC_PREFIX + ip2mac
        else:
            raise Exception(_('Please set external_host_ip conf. parameter '
                              'to enable SNAT application'))

    def switch_features_handler(self, ev):
        self._setup_patch_ports()
        self.external_bridge_mac = self.vswitch_api.get_port_mac_in_use(
            self.external_network_bridge) or const.EMPTY_MAC

        # install static strategy flows
        if self.external_host_ip is None:
            raise Exception(_('Please set external_host_ip conf. parameter '
                              'to enable SNAT application'))
        else:
            self.install_strategy_based_flows()

    def _setup_patch_ports(self):
        integration_bridge = cfg.CONF.df.integration_bridge
        ex_peer_patch_port = 'patch-snat-{0}'.format(
            self.external_network_bridge)
        int_peer_patch_port = 'patch-snat-int'

        mapping = self.vswitch_api.create_patch_pair(
            integration_bridge,
            self.external_network_bridge,
            ex_peer_patch_port,
            int_peer_patch_port)
        self.external_ofport = self.vswitch_api.get_port_ofport(
            mapping[0])

    @df_base_app.register_event(ovs.OvsPort, model_const.EVENT_CREATED)
    @df_base_app.register_event(ovs.OvsPort, model_const.EVENT_UPDATED)
    def ovs_port_updated(self, ovs_port, orig_ovs_port=None):
        if ovs_port.name != self.external_network_bridge:
            return

        LOG.debug("Ex. Bridge port update is called ... ")
        mac = ovs_port.mac_in_use
        if mac in (None, const.EMPTY_MAC, self.external_bridge_mac):
            return

        self.external_bridge_mac = mac

        if self.chassis is None:
            return

        parser = self.parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self._install_snat_egress_after_conntrack(
            match,
            self.external_host_mac)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _remove_local_port(self, lport):
        """override remove_local_port method to remove installed flows

        :param lport:  local logical port which is being removed
        """
        LOG.info("SNAT application: remove local port %(lport)s",
                 {'lport': lport})
        if self.external_host_mac is not None:
            # remove VM specific flows
            if self.is_data_port(lport):
                self.remove_lport_based_flows(lport)
            else:
                LOG.info('SNAT application: not a compute port, skipped')

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _add_local_port(self, lport):
        """override add_local_port method to install sNAT related flows

        :param lport:  local logical port which is being added
        """
        LOG.info("SNAT application: add local port %(lport)s",
                 {'lport': lport})

        if self.external_host_mac is not None:
            # install flows only when compute port is added
            if self.is_data_port(lport):
                self.chassis = lport.binding.chassis

                self.install_lport_based_flows(lport)
            else:
                LOG.info('SNAT application: not a compute port, skipped')

    def install_strategy_based_flows(self):

        if self.enable_goto_flows is True:
            self._install_ingress_goto_rules()
            self._install_egress_goto_rules()

        self._install_snat_ingress_conntrack()

        parser = self.parser
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP)
        self._install_snat_egress_conntrack(
            match,
            self.external_host_ip)
        self._install_snat_egress_after_conntrack(
            match,
            self.external_host_mac)

        self._install_arp_responder(
            self.external_host_ip,
            self.external_host_mac)

    def install_lport_based_flows(self, lport):
        # instance specific flows
        self._install_snat_ingress_after_conntrack(
                                        lport.unique_key,
                                        lport.mac,
                                        self.external_host_mac)

    def remove_lport_based_flows(self, lport):
        parser = self.parser
        ofproto = self.ofproto
        unique_key = lport.unique_key
        match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                ct_mark=int(unique_key))

        self.mod_flow(
            command=ofproto.OFPFC_DELETE_STRICT,
            table_id=const.INGRESS_SNAT_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)
