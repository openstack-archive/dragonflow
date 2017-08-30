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

from neutron_lib import constants as n_const
from oslo_log import log
from ryu.ofproto import ether

from dragonflow.controller.apps import l3_base
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app

LOG = log.getLogger(__name__)


class L3ProactiveApp(df_base_app.DFlowApp, l3_base.L3AppMixin):

    def packet_in_handler(self, event):
        msg = event.msg
        self.router_function_packet_in_handler(msg)

    def _add_subnet_send_to_route(self, match, local_network_id, router_port):
        self._add_subnet_send_to_proactive_routing(match, local_network_id,
                                                   router_port.mac)

    def _add_subnet_send_to_proactive_routing(self, match, dst_network_id,
                                              dst_router_port_mac):
        parser = self.parser
        ofproto = self.ofproto

        actions = []
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(metadata=dst_network_id))
        actions.append(parser.OFPActionSetField(eth_src=dst_router_port_mac))
        action_inst = parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.L3_PROACTIVE_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]

        self.mod_flow(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def _add_port(self, lport):
        """Add port which is not a router interface."""
        super(L3ProactiveApp, self)._add_port(lport)
        dst_ip = lport.ip
        dst_mac = lport.mac
        network_key = lport.lswitch.unique_key
        port_key = lport.unique_key

        # FIXME (dimak) need to take into account all fixed IPs
        self._add_port_process(dst_ip, dst_mac, network_key, port_key)

        for address_pair in lport.allowed_address_pairs:
            self._add_port_process(
                address_pair.ip_address,
                address_pair.mac_address,
                network_key,
                port_key,
            )

    def _add_port_process(self, dst_ip, dst_mac, network_id, tunnel_key,
                          priority=const.PRIORITY_HIGH):
        parser = self.parser
        ofproto = self.ofproto

        if dst_ip.version == n_const.IP_VERSION_4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=dst_ip)

        actions = []
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        actions.append(parser.OFPActionSetField(reg7=tunnel_key))
        action_inst = parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            inst=inst,
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _remove_port(self, lport):
        """Remove port which is not a router interface."""
        super(L3ProactiveApp, self)._remove_port(lport)
        dst_ip = lport.ip
        network_key = lport.lswitch.unique_key

        self._remove_port_process(dst_ip, network_key)

        for address_pair in lport.allowed_address_pairs:
            self._remove_port_process(address_pair.ip_address, network_key)

    def _remove_port_process(self, dst_ip, network_id,
                             priority=const.PRIORITY_HIGH):
        parser = self.parser
        ofproto = self.ofproto

        if dst_ip.version == n_const.IP_VERSION_4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=dst_ip)

        self.mod_flow(
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _update_port(self, lport, orig_lport):
        if (
            lport.ip != orig_lport.ip or
            lport.mac != orig_lport.mac or
            lport.allowed_address_pairs != orig_lport.allowed_address_pairs
        ):
            self._remove_port(orig_lport)
            self._add_port(lport)
