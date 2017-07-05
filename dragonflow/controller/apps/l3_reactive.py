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
from ryu.lib.packet import ipv4
from ryu.lib.packet import ipv6
from ryu.lib.packet import packet
from ryu.ofproto import ether

from dragonflow.controller.apps import l3_base
from dragonflow.controller.common import constants as const
from dragonflow.controller import df_base_app
from dragonflow.db.models import l2
from dragonflow.db.models import l3


LOG = log.getLogger(__name__)


# REVIST(xiaohhui): This is a randomly chosen number. Should this be unique
# for each router port?
ROUTER_PORT_BUFFER_ID = 0xff12


class L3ReactiveApp(df_base_app.DFlowApp, l3_base.L3AppMixin):
    def __init__(self, *args, **kwargs):
        super(L3ReactiveApp, self).__init__(*args, **kwargs)
        self.idle_timeout = 30
        self.hard_timeout = 0

    def packet_in_handler(self, event):
        msg = event.msg

        handled = self.router_function_packet_in_handler(msg)
        if handled:
            return

        # Normal path for a learn routing device.
        pkt = packet.Packet(msg.data)
        pkt_ip = pkt.get_protocol(ipv4.ipv4) or pkt.get_protocol(ipv6.ipv6)
        if pkt_ip is None:
            LOG.error("Received Non IP Packet")
            return
        network_id = msg.match.get('metadata')
        try:
            self._get_route(pkt_ip, network_id, msg)
        except Exception as e:
            LOG.error("L3 App PacketIn exception raised")
            LOG.error(e)

    def _get_route(self, pkt_ip, network_id, msg):
        ip_addr = netaddr.IPAddress(pkt_ip.dst)
        router_unique_key = msg.match.get('reg5')
        router = self.db_store.get_all(
            l3.LogicalRouter(unique_key=router_unique_key),
            l3.LogicalRouter.get_index('unique_key'))
        for router_port in router.ports:
            if ip_addr in router_port.network:
                index = l2.LogicalPort.get_index('lswitch_id')
                dst_ports = self.db_store.get_all(
                    l2.LogicalPort(lswitch=l2.LogicalSwitch(
                        id=router_port.lswitch.id)),
                    index=index)
                for out_port in dst_ports:
                    if out_port.ip == ip_addr:
                        self._install_l3_flow(router_port,
                                              out_port, msg,
                                              network_id)
                        return

    def _install_l3_flow(self, dst_router_port, dst_port, msg,
                         src_network_id):
        reg7 = dst_port.unique_key
        dst_ip = dst_port.ip
        src_mac = dst_router_port.mac
        dst_mac = dst_port.mac
        dst_network_id = dst_port.lswitch.unique_key

        parser = self.parser
        ofproto = self.ofproto

        if netaddr.IPAddress(dst_ip).version == n_const.IP_VERSION_4:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IP,
                                    metadata=src_network_id,
                                    ipv4_dst=dst_ip)
        else:
            match = parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6,
                                    metadata=src_network_id,
                                    ipv6_dst=dst_ip)

        actions = []
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(metadata=dst_network_id))
        actions.append(parser.OFPActionSetField(eth_src=src_mac))
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        actions.append(parser.OFPActionSetField(reg7=reg7))
        action_inst = parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions)

        goto_inst = parser.OFPInstructionGotoTable(const.EGRESS_TABLE)
        inst = [action_inst, goto_inst]

        # Since we are using buffer, set buffer id to make the new OpenFlow
        # rule carry on handling original packet.
        self.mod_flow(
            cookie=dst_router_port.unique_key,
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_VERY_HIGH,
            match=match,
            buffer_id=msg.buffer_id,
            idle_timeout=self.idle_timeout,
            hard_timeout=self.hard_timeout)

    def _add_subnet_send_to_route(self, match, local_network_id, router_port):
        self._add_subnet_send_to_controller(match)

    def _add_subnet_send_to_controller(self, match):
        parser = self.parser
        ofproto = self.ofproto

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ROUTER_PORT_BUFFER_ID)]
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            inst=inst,
            table_id=const.L3_LOOKUP_TABLE,
            priority=const.PRIORITY_MEDIUM,
            match=match)
