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

from neutron.common import constants as common_const

from ryu.ofproto import ether

from dragonflow.controller.common.arp_responder import ArpResponder
from dragonflow.controller.common import constants as const
from dragonflow.controller.df_base_app import DFlowApp

from oslo_log import log


LOG = log.getLogger(__name__)


class L3ProactiveApp(DFlowApp):
    def __init__(self, *args, **kwargs):
        super(L3ProactiveApp, self).__init__(*args, **kwargs)

    def switch_features_handler(self, ev):
        self.add_flow_go_to_table(self.get_datapath(),
                                  const.L3_LOOKUP_TABLE,
                                  const.PRIORITY_DEFAULT,
                                  const.EGRESS_TABLE)
        self._install_flows_on_switch_up()

    def add_router_port(self, router, router_port, local_network_id):
        datapath = self.get_datapath()
        parser = datapath.ofproto_parser

        mac = router_port.get_mac()
        tunnel_key = router_port.get_tunnel_key()
        dst_ip = router_port.get_ip()

        # Add router ARP responder for IPv4 Addresses
        if netaddr.IPAddress(router_port.get_ip()).version == 4:
            ArpResponder(datapath, local_network_id, dst_ip, mac).add()

        # If router interface IP, send to output table
        if netaddr.IPAddress(dst_ip).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=local_network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=local_network_id,
                                    ipv6_dst=dst_ip)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [goto_inst]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

        # Add router ip match go to output table
        self._install_flow_send_to_output_table(local_network_id,
                                                dst_ip)

        # Match all possible routeable traffic and send to proactive routing
        for port in router.get_ports():
            if port.get_id() != router_port.get_id():

                port_net_id = self.db_store.get_network_id(
                    port.get_lswitch_id(),
                )

                # From this router interface to all other interfaces
                self._add_subnet_send_to_proactive_routing(
                    local_network_id,
                    port.get_cidr_network(),
                    port.get_cidr_netmask(),
                    port.get_tunnel_key(),
                    port_net_id,
                    port.get_mac())

                # From all the other interfaces to this new interface
                self._add_subnet_send_to_proactive_routing(
                    port_net_id,
                    router_port.get_cidr_network(),
                    router_port.get_cidr_netmask(),
                    tunnel_key,
                    local_network_id,
                    router_port.get_mac())

    def _install_flow_send_to_output_table(self, network_id, dst_ip):

        parser = self.get_datapath().ofproto_parser
        if netaddr.IPAddress(dst_ip).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=dst_ip)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def _add_subnet_send_to_proactive_routing(self, network_id, dst_network,
                                              dst_netmask,
                                              dst_router_tunnel_key,
                                              dst_network_id,
                                              dst_router_port_mac):
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto

        if netaddr.IPAddress(dst_network).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=(dst_network, dst_netmask))
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=(dst_network, dst_netmask))

        actions = []
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(metadata=dst_network_id))
        actions.append(parser.OFPActionSetField(eth_src=dst_router_port_mac))
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)
        goto_inst = parser.OFPInstructionGotoTable(
            const.L3_PROACTIVE_LOOKUP_TABLE)

        inst = [action_inst, goto_inst]

        self.mod_flow(
            self.get_datapath(),
            cookie=dst_router_tunnel_key,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)

    def remove_router_port(self, router_port, local_network_id):

        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        tunnel_key = router_port.get_tunnel_key()

        if netaddr.IPAddress(router_port.get_ip()).version == 4:
            ip = router_port.get_ip()
            ArpResponder(self.get_datapath(), local_network_id, ip).remove()

        match = parser.OFPMatch()
        match.set_metadata(local_network_id)
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        match = parser.OFPMatch()
        cookie = tunnel_key
        self.mod_flow(
            datapath=self.get_datapath(),
            cookie=cookie,
            cookie_mask=cookie,
            table_id=const.L3_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_MEDIUM,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

        # Remove router port ip proactive flow
        if netaddr.IPAddress(router_port.get_ip()).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=local_network_id,
                                    ipv4_dst=router_port.get_ip())
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=local_network_id,
                                    ipv6_dst=router_port.get_ip())
        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def add_local_port(self, lport):
        self._add_port(lport)

    def add_remote_port(self, lport):
        self._add_port(lport)

    def _add_port(self, lport):
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            return
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        dst_ip = lport.get_ip()
        dst_mac = lport.get_mac()
        network_id = lport.get_external_value('local_network_id')
        tunnel_key = lport.get_tunnel_key()

        if netaddr.IPAddress(dst_ip).version == 4:
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
        action_inst = self.get_datapath().ofproto_parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]
        self.mod_flow(
            self.get_datapath(),
            inst=inst,
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            priority=const.PRIORITY_HIGH,
            match=match)

    def remove_local_port(self, lport):
        self._remove_port(lport)

    def remove_remote_port(self, lport):
        self._remove_port(lport)

    def _remove_port(self, lport):
        if lport.get_device_owner() == common_const.DEVICE_OWNER_ROUTER_INTF:
            return
        parser = self.get_datapath().ofproto_parser
        ofproto = self.get_datapath().ofproto
        dst_ip = lport.get_ip()
        network_id = lport.get_external_value('local_network_id')

        if netaddr.IPAddress(dst_ip).version == 4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=network_id,
                                    ipv6_dst=dst_ip)

        self.mod_flow(
            datapath=self.get_datapath(),
            table_id=const.L3_PROACTIVE_LOOKUP_TABLE,
            command=ofproto.OFPFC_DELETE,
            priority=const.PRIORITY_HIGH,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match)

    def _install_flows_on_switch_up(self):
        for lrouter in self.db_store.get_routers():
            for router_port in lrouter.get_ports():
                local_network_id = self.db_store.get_network_id(
                    router_port.get_lswitch_id(),
                )
                self.add_router_port(lrouter, router_port,
                        local_network_id)
        for lport in self.db_store.get_ports():
            self._add_port(lport)
