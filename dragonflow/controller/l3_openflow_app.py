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


import collections
import struct
import threading

from ryu.base import app_manager
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.ofproto import ether
from ryu.ofproto.ether import ETH_TYPE_8021Q
from ryu.ofproto import ofproto_v1_3

from ryu.lib.packet import arp
from ryu.lib.packet import ethernet
from ryu.lib.packet import packet

from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import icmp
from ryu.lib.packet import ipv4
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
from ryu.lib.packet import vlan

from ryu.lib import addrconv

from neutron import context

from neutron.common import constants as const
from neutron.i18n import _LE, _LI
from oslo_log import log

LOG = log.getLogger(__name__)

ETHERNET = ethernet.ethernet.__name__
VLAN = vlan.vlan.__name__
IPV4 = ipv4.ipv4.__name__
ICMP = icmp.icmp.__name__
TCP = tcp.tcp.__name__
UDP = udp.udp.__name__

VLANID_NONE = 0
VLANID_MIN = 2
VLANID_MAX = 4094
COOKIE_SHIFT_VLANID = 32
UINT16_MAX = 0xffff
UINT32_MAX = 0xffffffff
UINT64_MAX = 0xffffffffffffffff
OFPFW_NW_PROTO = 1 << 5

HIGH_PRIORITY_FLOW = 1000
MEDIUM_PRIORITY_FLOW = 100
NORMAL_PRIORITY_FLOW = 10
LOW_PRIORITY_FLOW = 1
LOWEST_PRIORITY_FLOW = 0


class AgentDatapath(object):
    """Represents a forwarding element switch local state"""

    def __init__(self):
        self.local_vlan_mapping = {}
        self.local_ports = None
        self.datapath = 0
        self.patch_port_num = 0

        # Dictionary used to hold port information received from OVS
        # each port data structure has a link to an entry in this dictionary
        # in 'switch_port_desc'
        self.switch_port_desc_dict = {}


class TenantTopology(object):
    """Represents a tenant topology"""

    def __init__(self, tenant_id):
        self.nodes = set()
        self.edges = collections.defaultdict(list)
        self.routers = {}
        self.distances = {}
        self.mac_to_port_data = collections.defaultdict(set)
        self.subnets = collections.defaultdict(set)
        self.tenant_id = tenant_id

    def add_router(self, router):
        self.routers[router.id] = router

    def del_router(self, router):
        del self.routers[router.id]

    def get_router_by_id(self, router_id):
        return self.routers[router_id]

    def add_node(self, value):
        self.nodes.add(value)

    def del_node(self, value):
        self.node.remove(value)

    def add_edge(self, from_node, to_node, distance):
        self.edges[from_node].append(to_node)
        self.edges[to_node].append(from_node)
        self.distances[(from_node, to_node)] = distance


class Router(object):

    def __init__(self, data):
        self.data = data
        self.subnets = {}

    def add_subnet(self, subnet):
        self.subnets[subnet.id] = subnet

    def remove_subnet(self, subnet):
        del self.subnets[subnet.id]

    @property
    def id(self):
        return self.data['id']

    @property
    def interfaces(self):
        return self.data.get('_interfaces', ())


class Subnet(object):

    def __init__(self, data, segmentation_id):
        self.data = data
        self.segmentation_id = segmentation_id

    @property
    def id(self):
        return self.data['id']

    @property
    def cidr(self):
        return self.data['cidr']

    @property
    def gateway_ip(self):
        return self.data['gateway_ip']

    def __repr__(self):
        return "<Subnet id='%s' cidr='%s' gateway_ip='%s'>" % (
            self.id,
            self.cidr,
            self.gateway_ip,
        )


class L3ReactiveApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    #OFP_VERSIONS = [ofproto_v1_2.OFP_VERSION]
    #OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]
    BASE_RPC_API_VERSION = '1.0'

    BASE_TABLE = 0
    CLASSIFIER_TABLE = 40
    METADATA_TABLE_ID = 50
    ARP_AND_BR_TABLE = 51
    L3_VROUTER_TABLE = 52

    def __init__(self, *args, **kwargs):
        super(L3ReactiveApp, self).__init__(*args, **kwargs)
        self.mac_to_port = {}

        self.ctx = context.get_admin_context()
        self.lock = threading.Lock()
        self._tenants = {}
        self.need_sync = True
        self.dp_list = {}

    def get_tenant_by_id(self, tenant_id):
        return self._tenants.setdefault(tenant_id, TenantTopology(tenant_id))

    def start(self):
        LOG.info(_LI("Starting Virtual L3 Reactive OpenFlow APP "))
        super(L3ReactiveApp, self).start()
        return 1

    def notify_sync(self):
        self.need_sync = True
        for switch in self.dp_list.values():
            datapath = switch.datapath
            self.send_port_desc_stats_request(datapath)

    def delete_router(self, router_id):
        for tenant in self._tenants.values():
            try:
                router = tenant.routers.pop(router_id)
            except KeyError:
                pass
            else:
                for interface in router.interfaces:
                    for subnet_info in router.interfaces['subnets']:
                        subnet = router.subnets[subnet_info['id']]
                        if subnet.segmentation_id == 0:
                            continue

                        for router in tenant.routers.values():
                            if subnet.id in router.subnets:
                                break
                        else:
                            del tenant.subnets[subnet.id]

                        self._remove_vrouter_arp_responder(
                            subnet.segmentation_id,
                            interface['mac_address'],
                            self.get_ip_from_interface(interface))

    def sync_router(self, router_info):
        LOG.info(_LI("sync_router --> %s"), router_info)

        tenant_topology = self.get_tenant_by_id(router_info['tenant_id'])

        router = Router(router_info)
        router_old = tenant_topology.routers.get(router.id)
        tenant_topology.add_router(router)
        subnets = tenant_topology.subnets

        for interface in router.interfaces:
            for subnet_info in interface['subnets']:
                subnet = subnets.setdefault(
                        subnet_info['id'],
                        Subnet(subnet_info, 0),
                )

                router.add_subnet(subnet)
                if subnet.segmentation_id != 0:
                    self._add_vrouter_arp_responder(
                        subnet.segmentation_id,
                        interface['mac_address'],
                        self.get_ip_from_interface(interface))

        # If previous definition of the router is known
        if router_old:
            # Handle removed subnets
            for interface in router_old.interfaces:
                for subnet_info in interface['subnets']:
                    subnet = router_old.subnets[subnet_info['id']]
                    if subnet.segmentation_id == 0:
                        continue

                    # if subnet was not deleted
                    if subnet.id in router.subnets:
                        continue

                    for router in tenant_topology.routers.values():
                        if subnet.id in router.subnets:
                            break
                    else:
                        del tenant_topology.subnets[subnet.id]

                    self._remove_vrouter_arp_responder(
                        subnet.segmentation_id,
                        interface['mac_address'],
                        self.get_ip_from_interface(interface))

    def attach_switch_port_desc_to_port_data(self, port_data):
        if 'id' in port_data:
            port_id = port_data['id']
            sub_str_port_id = str(port_id[0:11])

            # Only true if we already received port_desc from OVS
            for switch in self.dp_list.values():
                switch_port_desc_dict = switch.switch_port_desc_dict
                if sub_str_port_id in switch_port_desc_dict:
                    port_data['switch_port_desc'] = \
                          switch_port_desc_dict[sub_str_port_id]
                    port_desc = port_data['switch_port_desc']
                    self.add_flow_metadata_by_port_num(
                        port_desc['datapath'],
                        0,
                        HIGH_PRIORITY_FLOW,
                        port_desc['local_port_num'],
                        port_data['segmentation_id'],
                        0xffff,
                        self.CLASSIFIER_TABLE)

    def sync_port(self, port):
        LOG.info(_LI("sync_port--> %s\n"), port)

        tenant_topo = self.get_tenant_by_id(port['tenant_id'])
        subnets = tenant_topo.subnets
        if port['segmentation_id'] == 0:
            LOG.info(_LI("no segmentation data in port --> %s"), port)
            return

        tenant_topo.mac_to_port_data[port['mac_address']] = port
        subnets_ids = self.get_port_subnets(port)
        for subnet_id in subnets_ids:
            subnet = subnets.get(subnet_id)
            if not subnet:
                continue

            subnet.segmentation_id = port['segmentation_id']
            if port['device_owner'] == const.DEVICE_OWNER_ROUTER_INTF:
                self._add_vrouter_arp_responder(
                    subnet.segmentation_id,
                    port['mac_address'],
                    self.get_ip_from_interface(port))
            else:
                LOG.error(_LE("No subnet object for subnet %s"), subnet_id)

        self.attach_switch_port_desc_to_port_data(port)

    def get_port_subnets(self, port):
        subnets_ids = []
        if 'fixed_ips' in port:
            for fixed_ips in port['fixed_ips']:
                subnets_ids.append(fixed_ips['subnet_id'])
        return subnets_ids

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def OF_packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        if msg.reason == ofproto.OFPR_NO_MATCH:
            reason = 'NO MATCH'
        elif msg.reason == ofproto.OFPR_ACTION:
            reason = 'ACTION'
        elif msg.reason == ofproto.OFPR_INVALID_TTL:
            reason = 'INVALID TTL'
        else:
            reason = 'unknown'

        LOG.debug('OFPPacketIn received: '
                  'buffer_id=%x total_len=%d reason=%s '
                  'table_id=%d cookie=%d match=%s',
                  msg.buffer_id, msg.total_len, reason,
                  msg.table_id, msg.cookie, msg.match)
        # utils.hex_array(msg.data))
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        header_list = dict((p.protocol_name, p)
                           for p in pkt.protocols if not isinstance(p, str))
        if header_list:
            try:
                if "ipv4" in header_list:
                    self.handle_ipv4_packet_in(
                        datapath,
                        msg,
                        in_port,
                        header_list,
                        pkt,
                        eth)
                    return
                if "ipv6" in header_list:
                    self.handle_ipv6_packet_in(
                        datapath, in_port, header_list, pkt, eth)
                    return
            except Exception as exception:

                LOG.debug("Unable to handle packet %(msg)s: %(e)s",
                          {'msg': msg, 'e': exception})

        LOG.error(_LE(">>>>>>>>>> Unhandled  Packet>>>>>  %s"), pkt)

    def handle_ipv6_packet_in(self, datapath, in_port, header_list,
                              pkt, eth):
        # TODO(gampel)(gampel) add ipv6 support
        LOG.error(_LE("No handle for ipv6 yet should be offload to the"
                "NORMAL path  %s"), pkt)
        return

    def handle_ipv4_packet_in(self, datapath, msg, in_port, header_list, pkt,
                              eth):
        pkt_ipv4 = header_list['ipv4']
        pkt_ethernet = header_list['ethernet']
        switch = self.dp_list.get(datapath.id)
        if switch:
            if 'metadata' not in msg.match:
                # send request for loacl switch data
                self.send_port_desc_stats_request(datapath)
                LOG.error(_LE("No metadata on packet from %s"),
                          eth.src)
                return
            segmentation_id = msg.match['metadata']
            LOG.debug(
                "packet segmentation_id %s ",
                segmentation_id)
            for tenantid in self._tenants:
                tenant = self._tenants[tenantid]
                for router in tenant.routers.values():
                    for subnet in router.subnets.values():
                        if segmentation_id == subnet.segmentation_id:
                            LOG.debug("packet from  to tenant  %s ",
                                tenant.tenant_id)
                            in_port_data = self._tenants[
                                tenantid].mac_to_port_data[eth.src]
                            out_port_data = self._tenants[
                                tenantid].mac_to_port_data[eth.dst]
                            LOG.debug('Source port data <--- %s ',
                                in_port_data)
                            LOG.debug('Router Mac dest port data -> %s ',
                                out_port_data)
                            if self.handle_router_interface(datapath,
                                                            in_port,
                                                            out_port_data,
                                                            pkt,
                                                            pkt_ethernet,
                                                            pkt_ipv4) == 1:
                                # trafic to the virtual routre handle only
                                # ping
                                return
                            (dst_p_data,
                             dst_sub_id) = self.get_port_data(tenant,
                                                              pkt_ipv4.dst)
                            for _subnet in router.subnets.values():
                                if dst_sub_id == _subnet.data['id']:
                                    out_subnet = _subnet
                                    subnet_gw = out_subnet.data[
                                        'gateway_ip']

                                    (dst_gw_port_data,
                                     dst_gw_sub_id) = self.get_port_data(
                                        tenant, subnet_gw)

                                    if self.handle_router_interface(
                                            datapath,
                                            in_port,
                                            dst_gw_port_data,
                                            pkt,
                                            pkt_ethernet,
                                            pkt_ipv4) == 1:
                                        # this trafic to the virtual routre
                                        return
                                    if not dst_p_data:
                                        LOG.error(_LE("No local switch"
                                            "mapping for %s"),
                                            pkt_ipv4.dst)
                                        return
                                    if self.handle_router_interface(
                                            datapath,
                                            in_port,
                                            dst_p_data,
                                            pkt,
                                            pkt_ethernet,
                                            pkt_ipv4) != -1:
                                        # case for vrouter that is not the
                                        #gw and we are trying to  ping
                                        # this trafic to the virtual routre
                                        return

                                    LOG.debug("Installing flow Route %s-> %s",
                                        pkt_ipv4.src,
                                        pkt_ipv4.dst)
                                    self.install_l3_forwarding_flows(
                                        datapath,
                                        msg,
                                        in_port_data,
                                        in_port,
                                        segmentation_id,
                                        eth,
                                        pkt_ipv4,
                                        dst_gw_port_data,
                                        dst_p_data,
                                        out_subnet.segmentation_id)
                                    return

    def install_l3_forwarding_flows(self,
                                    datapath,
                                    msg,
                                    in_port_data,
                                    in_port,
                                    src_seg_id,
                                    eth,
                                    pkt_ipv4,
                                    dst_gw_port_data,
                                    dst_p_data,
                                    dst_seg_id):
        dst_p_desc = dst_p_data['switch_port_desc']
        in_port_desc = in_port_data['switch_port_desc']
        if dst_p_desc['local_dpid_switch'] == datapath.id:
            # The dst VM and the source VM are on the same compute Node
            # Send output flow directly to port, use the same datapath
            actions = self.add_flow_subnet_traffic(datapath,
                self.L3_VROUTER_TABLE,
                MEDIUM_PRIORITY_FLOW,
                in_port,
                src_seg_id,
                eth.src,
                eth.dst,
                pkt_ipv4.dst,
                pkt_ipv4.src,
                dst_gw_port_data['mac_address'],
                dst_p_data['mac_address'],
                dst_p_desc['local_port_num'])
            # Install the reverse flow return traffic
            self.add_flow_subnet_traffic(datapath,
                                         self.L3_VROUTER_TABLE,
                                         MEDIUM_PRIORITY_FLOW,
                                         dst_p_desc['local_port_num'],
                                         dst_seg_id,
                                         dst_p_data['mac_address'],
                                         dst_gw_port_data['mac_address'],
                                         pkt_ipv4.src,
                                         pkt_ipv4.dst,
                                         eth.dst,
                                         in_port_data['mac_address'],
                                         in_port_desc['local_port_num'])
            self.handle_packet_out_l3(datapath, msg, in_port, actions)
        else:
            # The dst VM and the source VM are NOT  on the same copute Node
            # Send output to br-tun patch port and install reverse flow on the
            # dst compute node
            remoteSwitch = self.dp_list.get(dst_p_desc['local_dpid_switch'])
            localSwitch = self.dp_list.get(datapath.id)
            actions = self.add_flow_subnet_traffic(datapath,
                                                   self.L3_VROUTER_TABLE,
                                                   MEDIUM_PRIORITY_FLOW,
                                                   in_port,
                                                   src_seg_id,
                                                   eth.src,
                                                   eth.dst,
                                                   pkt_ipv4.dst,
                                                   pkt_ipv4.src,
                                                   dst_gw_port_data[
                                                       'mac_address'],
                                                   dst_p_data[
                                                       'mac_address'],
                                                   localSwitch.patch_port_num,
                                                   dst_seg_id=dst_seg_id)
            # Remote reverse flow install
            self.add_flow_subnet_traffic(remoteSwitch.datapath,
                                         self.L3_VROUTER_TABLE,
                                         MEDIUM_PRIORITY_FLOW,
                                         dst_p_desc['local_port_num'],
                                         dst_seg_id,
                                         dst_p_data['mac_address'],
                                         dst_gw_port_data['mac_address'],
                                         pkt_ipv4.src,
                                         pkt_ipv4.dst,
                                         eth.dst,
                                         in_port_data['mac_address'],
                                         remoteSwitch.patch_port_num,
                                         dst_seg_id=src_seg_id)
            self.handle_packet_out_l3(datapath, msg, in_port, actions)

    def handle_packet_out_l3(self, datapath, msg, in_port, actions):
        data = None

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    def add_flow_subnet_traffic(self, datapath, table, priority, in_port,
                                src_seg_id, match_src_mac, match_dst_mac,
                                match_dst_ip, match_src_ip, src_mac,
                                dst_mac, out_port_num, dst_seg_id=None):
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_in_port(in_port)
        match.set_metadata(src_seg_id)
        match.set_dl_src(haddr_to_bin(match_src_mac))
        match.set_dl_dst(haddr_to_bin(match_dst_mac))
        match.set_ipv4_src(ipv4_text_to_int(str(match_src_ip)))
        match.set_ipv4_dst(ipv4_text_to_int(str(match_dst_ip)))
        actions = []
        inst = []
        ofproto = datapath.ofproto
        actions.append(parser.OFPActionDecNwTtl())
        actions.append(parser.OFPActionSetField(eth_src=src_mac))
        actions.append(parser.OFPActionSetField(eth_dst=dst_mac))
        if dst_seg_id:
            # The dest vm is on another compute machine so we must set the
            # segmentation Id and set metadata for the tunnel bridge to
            # for this flow
            field = parser.OFPActionSetField(tunnel_id=dst_seg_id)
            actions.append(field)
            goto_inst = parser.OFPInstructionGotoTable(60)
            #field = parser.OFPActionSetField(metadata=0x8000)
            #actions.append(field)
            #write_metadata = parser.OFPInstructionWriteMetadata(0x8000,0x8000)
            #inst= [write_metadata]
            inst.append(goto_inst)
            #inst.append(write_metadata)
        else:
            actions.append(parser.OFPActionOutput(out_port_num,
                                              ofproto.OFPCML_NO_BUFFER))
        inst.append(datapath.ofproto_parser.OFPInstructionActions(
                        ofproto.OFPIT_APPLY_ACTIONS, actions))
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match,
            out_port=out_port_num)

        return actions

    def add_flow_pop_vlan_to_normal(self, datapath, table, priority, vlan_id):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch(vlan_vid=0x1000 | vlan_id)
        #match = parser.OFPMatch(vlan_pcp=0)
        actions = [
            parser.OFPActionPopVlan(),
            parser.OFPActionOutput(
                ofproto.OFPP_NORMAL,
                ofproto.OFPCML_NO_BUFFER)]
        ofproto = datapath.ofproto
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match)

    def add_flow_normal_local_subnet(self, datapath, table, priority,
                                     dst_net, dst_mask, seg_id):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        #match = parser.OFPMatch(vlan_vid=0x1000| vlan_id)
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        #match.set_vlan_vid(0x1000 | vlan_id)
        match.set_metadata(seg_id)
        match.set_ipv4_dst_masked(ipv4_text_to_int(str(dst_net)),
                                  mask_ntob(int(dst_mask)))
        #match = parser.OFPMatch(vlan_pcp=0)
        actions = [
            #parser.OFPActionPopVlan(),
            parser.OFPActionOutput(
                ofproto.OFPP_NORMAL)]
        # actions = [parser.OFPActionOutput(ofproto.OFPP_NORMAL,
        #    ofproto.OFPCML_NO_BUFFER)]
        ofproto = datapath.ofproto
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match)

    def add_flow_normal_by_port_num(self, datapath, table, priority, in_port):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch(in_port=in_port)
        #match = parser.OFPMatch(vlan_pcp=0)
        actions = [parser.OFPActionOutput(ofproto.OFPP_NORMAL)]
        ofproto = datapath.ofproto
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match)

    def add_flow_metadata_by_port_num(self, datapath, table, priority,
                                      in_port, metadata,
                                      metadata_mask, goto_table):
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_in_port(in_port)
        goto_inst = parser.OFPInstructionGotoTable(goto_table)
        write_metadata = parser.OFPInstructionWriteMetadata(metadata,
                metadata_mask)
        inst = [write_metadata, goto_inst]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match)

    def add_flow_push_vlan_by_port_num(self, datapath, table, priority,
                                      in_port, dst_vlan, goto_table):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        match.set_in_port(in_port)
        field = parser.OFPMatchField.make(
            ofproto.OXM_OF_VLAN_VID, 0x1000 | dst_vlan)
        actions = [datapath. ofproto_parser. OFPActionPushVlan(
            ETH_TYPE_8021Q), datapath.ofproto_parser.OFPActionSetField(field)]
        goto_inst = parser.OFPInstructionGotoTable(goto_table)
        ofproto = datapath.ofproto
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions), goto_inst]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match)

    def delete_all_flow_from_table(self, datapath, table_id):

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        instructions = []
        flow_mod = datapath.ofproto_parser.OFPFlowMod(
            datapath,
            0,
            0,
            table_id,
            ofproto.OFPFC_DELETE,
            0,
            0,
            1,
            ofproto.OFPCML_NO_BUFFER,
            ofproto.OFPP_ANY,
            ofproto.OFPG_ANY,
            0,
            match,
            instructions)
        datapath.send_msg(flow_mod)

    def add_flow_normal(self, datapath, table, priority, match=None):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        #match = parser.OFPMatch(vlan_vid=0x1000)
        #match = parser.OFPMatch(vlan_pcp=0)
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_NORMAL)]
        ofproto = datapath.ofproto
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match)

    def mod_flow(self, datapath, cookie=0, cookie_mask=0, table_id=0,
                 command=None, idle_timeout=0, hard_timeout=0,
                 priority=0xff, buffer_id=0xffffffff, match=None,
                 actions=None, inst_type=None, out_port=None,
                 out_group=None, flags=0, inst=None):

        if command is None:
            command = datapath.ofproto.OFPFC_ADD

        if inst is None:
            if inst_type is None:
                inst_type = datapath.ofproto.OFPIT_APPLY_ACTIONS

            inst = []
            if actions is not None:
                inst = [datapath.ofproto_parser.OFPInstructionActions(
                    inst_type, actions)]

                if match is None:
                    match = datapath.ofproto_parser.OFPMatch()

        if out_port is None:
            out_port = datapath.ofproto.OFPP_ANY

        if out_group is None:
            out_group = datapath.ofproto.OFPG_ANY

        message = datapath.ofproto_parser.OFPFlowMod(datapath, cookie,
                                                     cookie_mask,
                                                     table_id, command,
                                                     idle_timeout,
                                                     hard_timeout,
                                                     priority,
                                                     buffer_id,
                                                     out_port,
                                                     out_group,
                                                     flags,
                                                     match,
                                                     inst)

        datapath.send_msg(message)

    def add_flow_go_to_table2(self, datapath, table, priority,
                              goto_table_id, match=None):
        inst = [datapath.ofproto_parser.OFPInstructionGotoTable(goto_table_id)]
        self.mod_flow(datapath, inst=inst, table_id=table, priority=priority,
                      match=match)

    def add_flow_goto_table_on_broad(self, datapath, table, priority,
                                     goto_table_id):
        match = datapath.ofproto_parser.OFPMatch(eth_dst='ff:ff:ff:ff:ff:ff')

        self.add_flow_go_to_table2(datapath, table, priority, goto_table_id,
                                   match)

    def add_flow_goto_table_on_mcast(self, datapath, table, priority,
                                     goto_table_id):
        #ofproto = datapath.ofproto
        match = datapath.ofproto_parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        self.add_flow_go_to_table2(datapath, table, priority, goto_table_id,
                                   match)

    def add_flow_go_to_table_on_arp(self, datapath, table, priority,
                                    goto_table_id):
        match = datapath.ofproto_parser.OFPMatch(eth_type=0x0806)
        self.add_flow_go_to_table2(datapath, table, priority, goto_table_id,
                                   match)

    def add_flow_go_to_table(self, datapath, table, priority, goto_table_id):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        actions = [parser.OFPInstructionGotoTable(goto_table_id)]
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath, cookie=0, cookie_mask=0, table_id=table,
            command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
            priority=priority, buffer_id=ofproto.OFP_NO_BUFFER,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            flags=0, match=match, instructions=inst)
        datapath.send_msg(mod)

    def add_flow_match_to_controller(self, datapath, table, priority,
                                     match=None, _actions=None):

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        ofproto = datapath.ofproto
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]

        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match)

    def add_flow_match_gw_mac_to_cont(self, datapath, dst_mac, table,
                                      priority, seg_id=None,
                                      _actions=None):
        parser = datapath.ofproto_parser
        #ofproto = datapath.ofproto
        match = parser.OFPMatch(eth_dst=dst_mac, metadata=seg_id)

        self.add_flow_match_to_controller(
            datapath, table, priority, match=match, _actions=_actions)

    def add_flow_l3(self, datapath, in_port, dst_mac, src_mac, vlan_vid,
                    actions):
        ofproto = datapath.ofproto

        match = datapath.ofproto_parser.OFPMatch(in_port=in_port,
                                                 eth_dst=dst_mac,
                                                 eth_src=src_mac,
                                                 vlan_vid=vlan_vid)
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath, cookie=0, cookie_mask=0, table_id=0,
            command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
            priority=0, buffer_id=ofproto.OFP_NO_BUFFER,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            flags=0, match=match, instructions=inst)
        datapath.send_msg(mod)

    def add_flow(self, datapath, port, dst, actions):
        ofproto = datapath.ofproto

        match = datapath.ofproto_parser.OFPMatch(in_port=port,
                                                 eth_dst=dst)
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath, cookie=0, cookie_mask=0, table_id=0,
            command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
            priority=0, buffer_id=ofproto.OFP_NO_BUFFER,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            flags=0, match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status_handler(self, ev):
        msg = ev.msg
        reason = msg.reason
        port_no = msg.desc.port_no
        datapath = ev.msg.datapath

        ofproto = msg.datapath.ofproto
        if reason == ofproto.OFPPR_ADD:
            LOG.info(_LI("port added %s"), port_no)
        elif reason == ofproto.OFPPR_DELETE:
            LOG.info(_LI("port deleted %s"), port_no)
        elif reason == ofproto.OFPPR_MODIFY:
            LOG.info(_LI("port modified %s"), port_no)
        else:
            LOG.info(_LI("Illeagal port state %(port_no)s %(reason)s")
                     % {'port_no': port_no, 'reason': reason})
        # TODO(gampel) Currently we update all the agents on modification
        LOG.info(_LI(" Updating flow table on agents got port update "))

        switch = self.dp_list.get(datapath.id)
        if switch:
            self.send_port_desc_stats_request(datapath)

    def add_bootstrap_flows(self, datapath):
        # Goto from main CLASSIFIER table
        self.add_flow_go_to_table2(datapath, 0, 1, self.CLASSIFIER_TABLE)
        # Send to controller unmatched inter subnet L3 traffic
        self.add_flow_match_to_controller(datapath, self.L3_VROUTER_TABLE, 0)
        #send L3 traffic unmatched to controller
        self.add_flow_go_to_table2(datapath, self.CLASSIFIER_TABLE, 1,
                                   self.L3_VROUTER_TABLE)
        #Goto from CLASSIFIER to ARP Table on ARP
        self.add_flow_go_to_table_on_arp(
            datapath,
            self.CLASSIFIER_TABLE,
            NORMAL_PRIORITY_FLOW,
            self.ARP_AND_BR_TABLE)
        #Goto from CLASSIFIER to ARP Table on broadcast
        #TODO(gampel) can go directly to NORMAL
        self.add_flow_goto_table_on_broad(
            datapath,
            self.CLASSIFIER_TABLE,
            MEDIUM_PRIORITY_FLOW,
            self.ARP_AND_BR_TABLE)
        #Goto from CLASSIFIER to ARP Table on mcast
        #TODO(gampel) can go directly to NORMAL
        self.add_flow_goto_table_on_mcast(
            datapath,
            self.CLASSIFIER_TABLE,
            NORMAL_PRIORITY_FLOW,
            self.ARP_AND_BR_TABLE)

        # Normal flow on arp table in low priority
        self.add_flow_normal(datapath, self.ARP_AND_BR_TABLE, 1)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        switch = self.dp_list.get(datapath.id)
        if not switch:
            self.dp_list[datapath.id] = AgentDatapath()
            self.dp_list[datapath.id].datapath = datapath
        # Normal flow with the lowset priority to send all traffic to NORMAL
        #until the bootstarp is done
        self.add_flow_normal(datapath, self.BASE_TABLE, 0)
        self.send_port_desc_stats_request(datapath)

    def send_port_desc_stats_request(self, datapath):
        ofp_parser = datapath.ofproto_parser

        req = ofp_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        ports = []
        datapath = ev.msg.datapath
        switch = self.dp_list.get(datapath.id)
        #self.delete_all_flow_from_table(datapath, self.BASE_TABLE)
        self.add_bootstrap_flows(datapath)
        for port in ev.msg.body:
            ports.append('port_no=%d hw_addr=%s name=%s config=0x%08x '
                         'state=0x%08x curr=0x%08x advertised=0x%08x '
                         'supported=0x%08x peer=0x%08x curr_speed=%d '
                         'max_speed=%d' %
                         (port.port_no, port.hw_addr,
                             port.name, port.config,
                             port.state, port.curr, port.advertised,
                             port.supported, port.peer, port.curr_speed,
                             port.max_speed))

            if port.name.startswith('tap'):
                LOG.debug(("Found DHCPD port  %s using MAC  %s"
                           "One machine install Special"
                           "(One Machine set up ) test use case"),
                          port.name,
                          port.hw_addr)
                self.add_flow_normal_by_port_num(
                    datapath, 0, HIGH_PRIORITY_FLOW, port.port_no)
            elif port.name.startswith('qvo'):
                # this is a VM port start with qvo<NET-ID[:11]> update the port
                # data with the port num and the switch dpid
                (port_id, mac, segmentation_id) = self.update_local_port_num(
                    port.name, port.port_no, datapath)
                if (segmentation_id != 0):
                    self.add_flow_metadata_by_port_num(datapath,
                                                       0,
                                                       HIGH_PRIORITY_FLOW,
                                                       port.port_no,
                                                       segmentation_id,
                                                       0xffff,
                                                       self.CLASSIFIER_TABLE)
                LOG.debug("Found VM  port  %s using MAC  %s  %d",
                          port.name, port.hw_addr, datapath.id)
            elif "patch-tun" in port.name:
                LOG.debug(("Found br-tun patch port %s %s --> NORMAL path"),
                        port.name, port.hw_addr)
                switch.patch_port_num = port.port_no
                self.add_flow_normal_by_port_num(
                    datapath, 0, HIGH_PRIORITY_FLOW, port.port_no)
        LOG.debug('OFPPortDescStatsReply received: %s', ports)
        switch.local_ports = ports
        #TODO(gampel) Install flows only for tenants with VMs running on
        #this specific compute node
        for tenantid in self._tenants:
            for router in self._tenants[tenantid].routers.values():
                for subnet in router.subnets.values():
                    for interface in router.data['_interfaces']:
                        for subnet_info in interface['subnets']:
                            if (subnet.data['id'] == subnet_info['id']
                                    and subnet.segmentation_id != 0):
                                segmentation_id = subnet.segmentation_id
                                network, net_mask = self.get_subnet_from_cidr(
                                    subnet.data['cidr'])

                                self.add_flow_normal_local_subnet(
                                    datapath,
                                    self.L3_VROUTER_TABLE,
                                    NORMAL_PRIORITY_FLOW,
                                    network,
                                    net_mask,
                                    segmentation_id)

                                self.add_flow_match_gw_mac_to_cont(
                                    datapath,
                                    interface['mac_address'],
                                    self.L3_VROUTER_TABLE,
                                    99,
                                    segmentation_id)
                                self._add_vrouter_arp_responder(
                                    subnet.segmentation_id,
                                    interface['mac_address'],
                                    self.get_ip_from_interface(interface))

    def send_features_request(self, datapath):
        ofp_parser = datapath.ofproto_parser

        req = ofp_parser.OFPFeaturesRequest(datapath)
        datapath.send_msg(req)

    def _send_packet(self, datapath, port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt.serialize()
        data = pkt.data
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)

    def get_l_vid_from_seg_id(self, switch, segmentation_id):
        for local_vlan in switch.local_vlan_mapping:
            if segmentation_id == switch.local_vlan_mapping[local_vlan]:
                return local_vlan
        return 0

    def update_local_port_num(self, port_name, port_num, datapath):

        dpid = datapath.id
        port_id_from_name = port_name[3:]
        switch_port_desc_dict = self.dp_list[dpid].switch_port_desc_dict
        switch_port_desc_dict[port_id_from_name] = {}
        switch_port_desc = switch_port_desc_dict[port_id_from_name]
        switch_port_desc['local_port_num'] = port_num
        switch_port_desc['local_dpid_switch'] = dpid
        switch_port_desc['datapath'] = datapath

        # If we already received port sync, link between the structures
        for tenantid in self._tenants:
            tenant = self._tenants[tenantid]
            for mac in tenant.mac_to_port_data:
                port_data = tenant.mac_to_port_data[mac]
                # print "port_data >>>>>>>>>>>>>>%s",port_data
                if 'id' in port_data:
                    port_id = port_data['id']
                    sub_str_port_id = str(port_id[0:11])
                    if sub_str_port_id == port_id_from_name:
                        port_data['switch_port_desc'] = switch_port_desc
                        return (
                            port_data['id'],
                            mac,
                            port_data['segmentation_id'])
                else:
                    LOG.error(_LE("No data in port data %s "), port_data)
        # This can happen if we received port description from OVS but didn't
        # yet received port_sync from the L3 service
        LOG.debug("Port data not found %s  num <%d> dpid <%d>", port_name,
                port_num, dpid)
        return(0, 0, 0)

    def get_port_data(self, tenant, ip_address):
        for mac in tenant.mac_to_port_data:
            port_data = tenant.mac_to_port_data[mac]
            if 'fixed_ips' in port_data:
                for fixed_ips in port_data['fixed_ips']:
                    if ip_address == fixed_ips['ip_address']:
                        return (port_data, fixed_ips['subnet_id'])

        return(0, 0)

    def get_ip_from_interface(self, interface):
        for fixed_ip in interface['fixed_ips']:
            if "ip_address" in fixed_ip:
                return fixed_ip['ip_address']

    def is_router_interface(self, port):
        if port['device_owner'] == 'network:router_interface':
            return True
        else:
            return False

    def handle_router_interface(self, datapath, in_port, port_data,
                                pkt, pkt_ethernet, pkt_ipv4):
        # retVal -1 -- dst  is not a v Router
        # retVal  1 -- The request was handled
        # retVal  0 -- router interface and the request was not handled
        retVal = -1
        if self.is_router_interface(port_data):
            # router mac address
            retVal = 0
            for fixed_ips in port_data['fixed_ips']:
                if pkt_ipv4.dst == fixed_ips['ip_address']:
                    # The dst ip address is the router Ip address should  be
                    # ping req
                    pkt_icmp = pkt.get_protocol(icmp.icmp)
                    if pkt_icmp:
                        # send ping responce
                        self._handle_icmp(
                            datapath,
                            in_port,
                            pkt_ethernet,
                            pkt_ipv4,
                            pkt_icmp)
                        LOG.debug("Sending ping echo -> ip %s ", pkt_ipv4.src)
                        retVal = 1
                    else:
                        LOG.error(_LE("any comunication to a router that"
                                   " is not ping should be dropped from"
                                   "ip  %s"),
                                   pkt_ipv4.src)
                        retVal = 1
        return retVal

    def send_flow_stats_request(self, datapath, table=None):

        ofp = datapath.ofproto
        ofp_parser = datapath.ofproto_parser
        if table is None:
            table = ofp.OFPTT_ALL
        cookie = cookie_mask = 0
        match = ofp_parser.OFPMatch()
        req = ofp_parser.OFPFlowStatsRequest(datapath, 0,
                                             table,
                                             ofp.OFPP_ANY, ofp.OFPG_ANY,
                                             cookie, cookie_mask,
                                             match)
        datapath.send_msg(req)

    def _handle_icmp(self, datapath, port, pkt_ethernet, pkt_ipv4, pkt_icmp):
        if pkt_icmp.type != icmp.ICMP_ECHO_REQUEST:
            return
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether.ETH_TYPE_IP,
                                           dst=pkt_ethernet.src,
                                           src=pkt_ethernet.dst))
        pkt.add_protocol(ipv4.ipv4(dst=pkt_ipv4.src,
                                   src=pkt_ipv4.dst,
                                   proto=pkt_ipv4.proto))
        pkt.add_protocol(icmp.icmp(type_=icmp.ICMP_ECHO_REPLY,
                                   code=icmp.ICMP_ECHO_REPLY_CODE,
                                   csum=0,
                                   data=pkt_icmp.data))
        self._send_packet(datapath, port, pkt)

    def check_direct_routing(self, tenant, from_subnet_id, to_subnet_id):
        return

    def get_subnet_from_cidr(self, cidr):
        split = cidr.split("/")
        return (split[0], split[1])

    def _get_match_vrouter_arp_responder(self, datapath, segmentation_id,
                                         interface_ip):
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_tpa(ipv4_text_to_int(str(interface_ip)))
        match.set_metadata(segmentation_id)
        return match

    def _get_inst_vrouter_arp_responder(self, datapath,
                                        mac_address, interface_ip):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionSetField(arp_op=arp.ARP_REPLY),
                   parser.NXActionRegMove(src_field='arp_sha',
                                          dst_field='arp_tha',
                                          n_bits=48),
                   parser.NXActionRegMove(src_field='arp_spa',
                                          dst_field='arp_tpa',
                                          n_bits=32),
                   parser.OFPActionSetField(arp_sha=mac_address),
                   parser.OFPActionSetField(arp_spa=interface_ip),
                   parser.OFPActionOutput(ofproto.OFPP_IN_PORT, 0)]
        instructions = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return instructions

    def _add_vrouter_arp_responder(self, segmentation_id,
                                   mac_address, interface_ip):
        LOG.debug("adding %(segmentation_id)s, %(mac_address)s, "
                  "%(interface_ip)s",
                  {'segmentation_id': segmentation_id,
                   'mac_address': mac_address,
                   'interface_ip': interface_ip})
        for switch in self.dp_list.values():
            datapath = switch.datapath
            match = self._get_match_vrouter_arp_responder(
                datapath, segmentation_id, interface_ip)
            instructions = self._get_inst_vrouter_arp_responder(
                datapath, mac_address, interface_ip)
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            msg = parser.OFPFlowMod(datapath=datapath,
                                    table_id=L3ReactiveApp.ARP_AND_BR_TABLE,
                                    command=ofproto.OFPFC_ADD,
                                    priority=MEDIUM_PRIORITY_FLOW,
                                    match=match, instructions=instructions,
                                    flags=ofproto.OFPFF_SEND_FLOW_REM)
            datapath.send_msg(msg)

    def _remove_vrouter_arp_responder(self, segmentation_id, mac_address,
                                      interface_ip):
        LOG.debug("removing %(segmentation_id)s, %(mac_address)s, "
                  "%(interface_ip)s",
                  {'segmentation_id': segmentation_id,
                   'mac_address': mac_address,
                   'interface_ip': interface_ip})
        for switch in self.dp_list.values():
            datapath = switch.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match = self._get_match_vrouter_arp_responder(
                datapath, segmentation_id, interface_ip)
            msg = parser.OFPFlowMod(datapath=datapath,
                                    cookie=0,
                                    cookie_mask=0,
                                    table_id=L3ReactiveApp.ARP_AND_BR_TABLE,
                                    command=ofproto.OFPFC_DELETE,
                                    priority=MEDIUM_PRIORITY_FLOW,
                                    out_port=ofproto.OFPP_ANY,
                                    out_group=ofproto.OFPG_ANY,
                                    match=match)
            datapath.send_msg(msg)

# Base static


def ipv4_apply_mask(address, prefix_len, err_msg=None):
    #                import itertools
    assert isinstance(address, str)
    address_int = ipv4_text_to_int(address)
    return ipv4_int_to_text(address_int & mask_ntob(prefix_len, err_msg))


def ipv4_text_to_int(ip_text):
    if ip_text == 0:
        return ip_text
    assert isinstance(ip_text, str)
    return struct.unpack('!I', addrconv.ipv4.text_to_bin(ip_text))[0]


def ipv4_int_to_text(ip_int):
    assert isinstance(ip_int, (int, long))
    return addrconv.ipv4.bin_to_text(struct.pack('!I', ip_int))


def mask_ntob(mask, err_msg=None):
    try:
        return (UINT32_MAX << (32 - mask)) & UINT32_MAX
    except ValueError:
        msg = 'illegal netmask'
        if err_msg is not None:
            msg = '%s %s' % (err_msg, msg)
            raise ValueError(msg)
