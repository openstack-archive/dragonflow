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

from oslo_config import cfg

from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app


class BridgeConnector(df_base_app.DFlowApp):
    """Implements connectivity between external and internal OVS bridges

    Required by SNAT/DNAT applications
    """
    def __init__(self, *args, **kwargs):
        super(BridgeConnector, self).__init__(*args, **kwargs)
        self.external_network_bridge = \
            cfg.CONF.df_snat_app.external_network_bridge
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.int_peer_patch_port = \
            cfg.CONF.df_connector_app.int_peer_patch_port
        self.ex_peer_patch_port = \
            cfg.CONF.df_connector_app.ex_peer_patch_port

    def switch_features_handler(self, ev):
        self._init_external_bridge()
        self._install_output_to_physical_patch(self.external_ofport)

    def _init_external_bridge(self):
        if not self.vswitch_api.patch_port_exist(self.ex_peer_patch_port):
            self.external_ofport = self.vswitch_api.create_patch_port(
                self.integration_bridge,
                self.ex_peer_patch_port,
                self.int_peer_patch_port)
            self.vswitch_api.create_patch_port(
                self.external_network_bridge,
                self.int_peer_patch_port,
                self.ex_peer_patch_port)
        else:
            self.external_ofport = self.vswitch_api.get_port_ofport(
                self.ex_peer_patch_port)

    def _install_output_to_physical_patch(self, ofport):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        actions = [parser.OFPActionOutput(ofport,
                                          ofproto.OFPCML_NO_BUFFER)]
        actions_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        inst = [actions_inst]
        self.mod_flow(self.get_datapath(), inst=inst,
                      table_id=const.EGRESS_EXTERNAL_TABLE,
                      priority=const.PRIORITY_MEDIUM, match=None)
