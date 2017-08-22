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

from neutron_lib.utils import helpers
from oslo_log import log
from ryu.lib import mac as mac_api
from ryu.ofproto import nicira_ext

from dragonflow.common import utils
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as const
from dragonflow.controller.common import logical_networks
from dragonflow.controller import df_base_app
from dragonflow.db.models import constants as model_const
from dragonflow.db.models import l2
from dragonflow.db.models import ovs


NET_VLAN = 'vlan'
NET_FLAT = 'flat'
NETWORK_TYPES = (NET_VLAN, NET_FLAT)
VLAN_TAG_BITS = 12
VLAN_MASK = utils.get_bitmask(VLAN_TAG_BITS)

LOG = log.getLogger(__name__)


class ProviderApp(df_base_app.DFlowApp):
    def __init__(self, *args, **kwargs):
        super(ProviderApp, self).__init__(*args, **kwargs)
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.logical_networks = logical_networks.LogicalNetworks()
        self.bridge_mappings = self._parse_bridge_mappings(
                cfg.CONF.df_provider_networks.bridge_mappings)
        self.reverse_bridge_mappings = {
            v: k for (k, v) in self.bridge_mappings.items()
        }
        self.int_ofports = {}
        self.bridge_macs = {}

    def _parse_bridge_mappings(self, bridge_mappings):
        try:
            return helpers.parse_mappings(bridge_mappings)
        except ValueError:
            LOG.exception("Failed to parse bridge mapping")
            raise

    def _setup_physical_bridges(self, bridge_mappings):
        '''Setup the physical network bridges.

           Creates physical network bridges and links them to the
           integration bridge using veths or patch ports.

           :param bridge_mappings: map physical network names to bridge names.
        '''
        for physical_network, bridge in bridge_mappings.items():
            LOG.info("Mapping physical network %(physical_network)s to "
                     "bridge %(bridge)s",
                     {'physical_network': physical_network,
                      'bridge': bridge})
            mappings = self.vswitch_api.create_patch_pair(
                self.integration_bridge, bridge)

            self.int_ofports[physical_network] = \
                self.vswitch_api.get_port_ofport(
                        mappings[0])

            mac = self.vswitch_api.get_port_mac_in_use(bridge)
            self.bridge_macs[physical_network] = mac

    @df_base_app.register_event(ovs.OvsPort, model_const.EVENT_CREATED)
    @df_base_app.register_event(ovs.OvsPort, model_const.EVENT_UPDATED)
    def _bridge_updated(self, ovsport, orig_ovsport=None):
        self._update_bridge_mac(ovsport.name, ovsport.mac_in_use)

    @df_base_app.register_event(ovs.OvsPort, model_const.EVENT_DELETED)
    def _bridge_deleted(self, ovsport):
        self._update_bridge_mac(ovsport.name, None)

    def _update_bridge_mac(self, bridge, mac):
        if bridge not in self.bridge_macs:
            return

        old_mac = self.bridge_macs[bridge]
        if old_mac == mac:
            return

        physical_network = self.reverse_bridge_mappings[bridge]
        lswitch = self.db_store.get_one(
            l2.LogicalSwitch(physical_network=physical_network),
            index=l2.LogicalSwitch.get_index('physical_network'))

        if old_mac is not None:
            self._remove_egress_placeholder_flow(lswitch.unique_key)

        if mac is not None:
            self._egress_placeholder_flow(lswitch.unique_key)

        self.bridge_macs[physical_network] = mac

    def switch_features_handler(self, ev):
        self._setup_physical_bridges(self.bridge_mappings)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_BIND_LOCAL)
    def _add_local_port(self, lport):
        lswitch = lport.lswitch
        network_type = lswitch.network_type
        if network_type not in NETWORK_TYPES:
            return
        network_id = lswitch.unique_key
        port_count = self.logical_networks.get_local_port_count(
                network_id=network_id,
                network_type=network_type)
        LOG.info("adding %(net_type)s local port %(lport)s",
                 {'net_type': network_type,
                  'lport': lport})
        if port_count == 0:
            self._new_network_flow(lport,
                                   network_id,
                                   network_type)
        self.logical_networks.add_local_port(port_id=lport.id,
                                             network_id=network_id,
                                             network_type=network_type)

    def _match_actions_by_network_type(self, lport, network_id, network_type):
        actions = [
            self.parser.NXActionRegLoad(
                dst='in_port',
                value=0,
                ofs_nbits=nicira_ext.ofs_nbits(0, 31),
            ),
            self.parser.OFPActionSetField(metadata=network_id),
        ]

        if network_type == NET_VLAN:
            vlan_vid = self.ofproto.OFPVID_PRESENT
            vlan_vid |= lport.lswitch.segmentation_id
            actions.append(self.parser.OFPActionPopVlan())
        elif network_type == NET_FLAT:
            vlan_vid = 0

        match = self.parser.OFPMatch(
            in_port=self.int_ofports[lport.lswitch.physical_network],
            vlan_vid=vlan_vid,
        )

        return match, actions

    def _new_network_flow(self, lport, network_id, network_type):
        LOG.debug('new %(net_type)s network: %(net_id)s',
                  {'net_type': network_type,
                   'net_id': network_id})
        self._network_classification_flow(lport, network_id, network_type)
        self._l2_lookup_flow(network_id)
        self._egress_flow(lport, network_id, network_type)
        self._egress_external_flow(lport, network_id)

    def _l2_lookup_flow(self, network_id):
        LOG.debug('l2 lookup flow for network %(net_id)s',
                  {'net_id': network_id})

        match = self._make_bum_match(metadata=network_id)
        inst = [self.parser.OFPInstructionGotoTable(const.EGRESS_TABLE)]
        self.mod_flow(
            inst=inst,
            table_id=const.L2_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _egress_flow(self, lport, network_id, network_type):
        LOG.debug('Add egress flow for network %(net_id)s',
                  {'net_id': network_id})
        inst = [self.parser.OFPInstructionGotoTable(
                const.EGRESS_EXTERNAL_TABLE)]
        if network_type == NET_VLAN:
            segmentation_id = lport.lswitch.segmentation_id
            vlan_tag = (segmentation_id & VLAN_MASK)
            # from open flow documentation:
            # https://www.opennetworking.org/images/stories/downloads/\
            #       sdn-resources/onf-specifications/openflow/\
            #       openflow-spec-v1.3.3.pdf
            # "... in particular the OFPVID_PRESENT bit must be set in
            # OXM_OF_VLAN_VID set-field actions."
            vlan_tag |= self.ofproto.OFPVID_PRESENT
            actions = [
                    self.parser.OFPActionPushVlan(),
                    self.parser.OFPActionSetField(vlan_vid=vlan_tag)]
            action_inst = self.parser.OFPInstructionActions(
                    self.ofproto.OFPIT_APPLY_ACTIONS,
                    actions)
            inst.insert(0, action_inst)
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=self.parser.OFPMatch(metadata=network_id),
            inst=inst,
        )

        # Drop all packets that did not originate on current node.
        # Any packet arriving from provider network won't have reg6 set.
        self.mod_flow(
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW + 1,
            match=self.parser.OFPMatch(
                metadata=network_id,
                reg6=0,
            ),
            inst=None,
        )

    def _egress_external_flow(self, lport, network_id):
        LOG.debug('Add egress external flow for network %(net_id)s',
                  {'net_id': network_id})

        physical_network = lport.lswitch.physical_network
        ofport = self.int_ofports[physical_network]

        # Output without updating MAC:
        self.mod_flow(
            table_id=const.EGRESS_EXTERNAL_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=self.parser.OFPMatch(metadata=network_id),
            inst=[
                self.parser.OFPInstructionActions(
                    self.ofproto.OFPIT_APPLY_ACTIONS,
                    [
                        self.parser.OFPActionOutput(
                            ofport,
                            self.ofproto.OFPCML_NO_BUFFER,
                        ),
                    ]
                ),
            ],
        )

        if self.bridge_macs.get(physical_network) is not None:
            self._egress_placeholder_flow(lport)

    def _egress_placeholder_flow(self, lport):
        # If dest MAC is the placeholder, update it to bridge MAC
        network_id = lport.lswitch.unique_key
        physical_network = lport.lswitch.physical_network
        ofport = self.int_ofports[physical_network]

        self.mod_flow(
            table_id=const.EGRESS_EXTERNAL_TABLE,
            priority=const.PRIORITY_HIGH,
            match=self.parser.OFPMatch(
                metadata=network_id,
                eth_dst=const.EMPTY_MAC,
            ),
            inst=[
                self.parser.OFPInstructionActions(
                    self.ofproto.OFPIT_APPLY_ACTIONS,
                    [
                        self.parser.OFPActionSetField(
                            eth_dst=self.bridge_macs[physical_network],
                        ),
                        self.parser.OFPActionOutput(
                            ofport,
                            self.ofproto.OFPCML_NO_BUFFER,
                        ),
                    ]
                ),
            ],
        )

    def _network_classification_flow(self, lport, network_id, network_type):
        LOG.debug('network classification flow for network_id: %(net_id)s',
                  {'net_id': network_id})
        match, actions = self._match_actions_by_network_type(lport,
                                                             network_id,
                                                             network_type)
        action_inst = self.parser.OFPInstructionActions(
            self.ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = self.parser.OFPInstructionGotoTable(const.L2_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    @df_base_app.register_event(l2.LogicalPort, l2.EVENT_UNBIND_LOCAL)
    def _remove_local_port(self, lport):
        network_type = lport.lswitch.network_type
        if network_type not in NETWORK_TYPES:
            return
        network_id = lport.lswitch.unique_key
        self.logical_networks.remove_local_port(port_id=lport.id,
                                                network_id=network_id,
                                                network_type=network_type)
        port_count = self.logical_networks.get_local_port_count(
                network_id=network_id,
                network_type=network_type)
        if port_count == 0:
            self._remove_network_flow(lport, network_id, network_type)

    def _remove_network_flow(self, lport, network_id, network_type):
        self._remove_network_classification_flow(lport,
                                                 network_id,
                                                 network_type)
        self._remove_l2_lookup_flow(network_id)
        self._remove_egress_flow(network_id)
        self._remove_egress_external_flow(network_id)

    def _remove_network_classification_flow(self,
                                            lport,
                                            network_id,
                                            network_type):
        match, actions = self._match_actions_by_network_type(lport,
                                                             network_id,
                                                             network_type)
        self.mod_flow(
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _remove_l2_lookup_flow(self, network_id):
        match = self._make_bum_match(metadata=network_id)
        self.mod_flow(
            table_id=const.L2_LOOKUP_TABLE,
            command=self.ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _remove_egress_flow(self, network_id):
        match = self.parser.OFPMatch(metadata=network_id)
        self.mod_flow(
            command=self.ofproto.OFPFC_DELETE,
            table_id=const.EGRESS_TABLE,
            priority=const.PRIORITY_LOW,
            match=match)

    def _remove_egress_external_flow(self, network_id):
        match = self.parser.OFPMatch(metadata=network_id)
        self.mod_flow(
                command=self.ofproto.OFPFC_DELETE,
                table_id=const.EGRESS_EXTERNAL_TABLE,
                priority=const.PRIORITY_HIGH,
                match=match)

        # This removes the placeholder flow as well

    def _remove_egress_placeholder_flow(self, network_id):
        self.mod_flow(
                command=self.ofproto.OFPFC_DELETE,
                table_id=const.EGRESS_EXTERNAL_TABLE,
                priority=const.PRIORITY_HIGH,
                match=self.parser.OFPMatch(
                    metadata=network_id,
                    eth_dst=const.EMPTY_MAC,
                ),
        )

    def _make_bum_match(self, metadata):
        match = self.parser.OFPMatch()
        match.set_metadata(metadata)
        encoded_mac = mac_api.haddr_to_bin(mac_api.DONTCARE_STR)
        encoded_mask = mac_api.haddr_to_bin(mac_api.UNICAST)
        match.set_dl_dst_masked(encoded_mac, encoded_mask)
        return match
