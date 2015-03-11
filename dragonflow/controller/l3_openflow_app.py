# Copyright (c) 2014 OpenStack Foundation.
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
from neutron import manager

from neutron.common import constants as const
from neutron.openstack.common import log
from neutron.plugins.common import constants as service_constants

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

HIGH_PRIOREITY_FLOW = 1000
MEDIUM_PRIOREITY_FLOW = 100
NORMAL_PRIOREITY_FLOW = 10
LOW_PRIOREITY_FLOW = 1
LOWEST_PRIOREITY_FLOW = 0


# A class to represent a  forwarding Elemnt Switch local state
class AgentDatapath(object):

    def __init__(self):
        self.local_vlan_mapping = {}
        self.local_ports = None
        self.datapath = 0
        self.patch_port_num = 0


# A class to represent tenat toplogie
class TenantTopo(object):

    def __init__(self):
        self.nodes = set()
        self.edges = collections.defaultdict(list)
        self.routers = []
        self.distances = {}
        self.mac_to_port_data = collections.defaultdict(set)
        self.subnet_array = collections.defaultdict(set)
        self.tenant_id = None
        #self.segmentation_id = None

    def add_router(self, router, r_id):
        self.routers.append(router)

    def add_node(self, value):
        self.nodes.add(value)

    def add_edge(self, from_node, to_node, distance):
        self.edges[from_node].append(to_node)
        self.edges[to_node].append(from_node)
        self.distances[(from_node, to_node)] = distance


class Router(object):

    def __init__(self, data):
        self.data = data
        self.subnets = []

    def add_subnet(self, subnet, sub_id):
        self.subnets.append(subnet)


class Subnet(object):

    def __init__(self, data, port_data, segmentation_id):
        self.data = data
        self.port_data = port_data
        self.segmentation_id = segmentation_id


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
        self.tenants = collections.defaultdict(lambda: None)
        self.need_sync = True
        self.dp_list = {}

    def start(self):
        self.logger.info("Starting Virtual L3 Reactive OpenFlow APP ")
        super(L3ReactiveApp, self).start()
        return 1

    def notify_sync(self):
        self.need_sync = True
        for dpid in self.dp_list:
            datapath = self.dp_list[dpid].datapath
            self.send_features_request(datapath)
            self.send_port_desc_stats_request(datapath)

    def sync_router(self, router):
        LOG.info(("sync_router --> %s"), router)
        tenant_id = router['tenant_id']
        if not router['tenant_id'] in self.tenants:
            self.tenants[router['tenant_id']] = TenantTopo()
        tenant_topo = self.tenants[router['tenant_id']]
        tenant_topo.tenant_id = tenant_id
        router_cls = Router(router)
        tenant_topo.add_router(router_cls, router['id'])
        subnets_array = tenant_topo.subnet_array
        l3plugin = manager.NeutronManager.get_service_plugins().get(
            service_constants.L3_ROUTER_NAT)

        if "_interfaces" in router:
            for interface in router['_interfaces']:
                # tenant_topo.add_router(router,router['id'])
                subnet_id = interface['subnet']['id']
                if subnet_id not in subnets_array:
                    subnets_array[subnet_id] = Subnet(interface['subnet'],
                                        None,
                                        0)
                subnet_cls = subnets_array[subnet_id]
                router_cls.add_subnet(subnet_cls,
                                      interface['subnet']['id'])
                if subnets_array[subnet_id].segmentation_id != 0:
                    l3plugin.setup_vrouter_arp_responder(
                        self.ctx,
                        "br-int",
                        "add",
                        self.ARP_AND_BR_TABLE,
                        subnets_array[subnet_id].segmentation_id,
                        interface['network_id'],
                        interface['mac_address'],
                        self.get_ip_from_interface(interface))

    def sync_port(self, port):
        port_data = port
        LOG.info(("sync_port--> %s\n"), port_data)
        l3plugin = manager.NeutronManager.get_service_plugins().get(
            service_constants.L3_ROUTER_NAT)
        tenant_id = port_data['tenant_id']
        if tenant_id not in self.tenants:
            self.tenants[tenant_id] = TenantTopo()
        tenant_topo = self.tenants[tenant_id]
        subnets_array = tenant_topo.subnet_array
        if port_data['segmentation_id'] != 0:
            tenant_topo.mac_to_port_data[port_data['mac_address']] = port_data
            tenant_topo.subnet_array[port_data['mac_address']] = port_data
            subnets_ids = self.get_port_subnets(port_data)
            for subnet_id in subnets_ids:
                if subnet_id in subnets_array:
                    subnet = subnets_array[subnet_id]
                    subnet.segmentation_id = port_data['segmentation_id']
                    if port['device_owner'] == const.DEVICE_OWNER_ROUTER_INTF:
                        l3plugin.setup_vrouter_arp_responder(
                            self.ctx,
                            "br-int",
                            "add",
                            self.ARP_AND_BR_TABLE,
                            subnet.segmentation_id,
                            port['network_id'],
                            port['mac_address'],
                            self.get_ip_from_interface(port))
                else:
                    LOG.error(("No subnet object for subnet %s"), subnet_id)
        else:
            LOG.info(("no segmentation data in port --> %s"), port_data)

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

        LOG.error(">>>>>>>>>> Unhandled  Packet>>>>>  %s", pkt)

    def handle_ipv6_packet_in(self, datapath, in_port, header_list,
                              pkt, eth):
        # TODO(gampel)(gampel) add ipv6 support
        LOG.error(("No handle for ipv6 yet should be offload to the"
                   "NORMAL path  %s", pkt))
        return

    def handle_ipv4_packet_in(self, datapath, msg, in_port, header_list, pkt,
                              eth):
        pkt_ipv4 = header_list['ipv4']
        pkt_ethernet = header_list['ethernet']
        switch = self.dp_list.get(datapath.id)
        if switch:
            if 'metadata' not in msg.match:
                # send request for loacl switch data
                # self.send_port_desc_stats_request(datapath)
                #self.send_flow_stats_request(
                #    datapath, table=self.METADATA_TABLE_ID)
                LOG.error(("No metadata on packet from %s"),
                          eth.src)
                return
            segmentation_id = msg.match['metadata']
            self.logger.info(
                "packet segmentation_id %s ",
                segmentation_id)
            for tenantid in self.tenants:
                tenant = self.tenants[tenantid]
                for router in tenant.routers:
                    for subnet in router.subnets:
                        if segmentation_id == subnet.segmentation_id:
                            self.logger.info("packet from  to tenant  %s ",
                                             tenant.tenant_id)
                            in_port_data = self.tenants[
                                tenantid].mac_to_port_data[eth.src]
                            out_port_data = self.tenants[
                                tenantid].mac_to_port_data[eth.dst]
                            LOG.debug(('Source port data <--- %s ',
                                       in_port_data))
                            LOG.debug(('Router Mac dest port data -> %s ',
                                       out_port_data))
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
                            for _subnet in router.subnets:
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
                                        LOG.error(("No local switch"
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

                                    LOG.debug(("Route from  %s to %s"
                                               "exist installing flow ",
                                               pkt_ipv4.src,
                                               pkt_ipv4.dst))
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
        if dst_p_data['local_dpid_switch'] == datapath.id:
            # The dst VM and the source VM are on the same copute Node
            # Send output flow directly to port iuse the same datapath
            actions = self.add_flow_subnet_traffic(datapath,
                self.L3_VROUTER_TABLE,
                MEDIUM_PRIOREITY_FLOW,
                in_port,
                src_seg_id,
                eth.src,
                eth.dst,
                pkt_ipv4.dst,
                pkt_ipv4.src,
                dst_gw_port_data['mac_address'],
                dst_p_data['mac_address'],
                dst_p_data['local_port_num'])
            # Install the reverse flow return traffic
            self.add_flow_subnet_traffic(datapath,
                                         self.L3_VROUTER_TABLE,
                                         MEDIUM_PRIOREITY_FLOW,
                                         dst_p_data['local_port_num'],
                                         dst_seg_id,
                                         dst_p_data['mac_address'],
                                         dst_gw_port_data['mac_address'],
                                         pkt_ipv4.src,
                                         pkt_ipv4.dst,
                                         eth.dst,
                                         in_port_data['mac_address'],
                                         in_port_data['local_port_num'])
            self.handle_packet_out_l3(datapath, msg, in_port, actions)
        else:
            # The dst VM and the source VM are NOT  on the same copute Node
            # Send output to br-tun patch port and install reverse flow on the
            # dst compute node
            remoteSwitch = self.dp_list.get(dst_p_data['local_dpid_switch'])
            localSwitch = self.dp_list.get(datapath.id)
            actions = self.add_flow_subnet_traffic(datapath,
                                                   self.L3_VROUTER_TABLE,
                                                   MEDIUM_PRIOREITY_FLOW,
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
                                         MEDIUM_PRIOREITY_FLOW,
                                         dst_p_data['local_port_num'],
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
        ofproto = datapath.ofproto
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
            self.logger.info("port added %s", port_no)
        elif reason == ofproto.OFPPR_DELETE:
            self.logger.info("port deleted %s", port_no)
        elif reason == ofproto.OFPPR_MODIFY:
            self.logger.info("port modified %s", port_no)
        else:
            self.logger.info("Illeagal port state %s %s", port_no, reason)
        # TODO(gampel) Currently we update all the agents on modification
        LOG.info((" Updating flow table on agents got port update "))

        switch = self.dp_list.get(datapath.id)
        if switch:
            self.send_port_desc_stats_request(datapath)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        switch = self.dp_list.get(datapath.id)
        if not switch:
            self.dp_list[datapath.id] = AgentDatapath()
            self.dp_list[datapath.id].datapath = datapath
        self.send_port_desc_stats_request(datapath)
        # main table 0  to Arp On ARp or broadcat or multicast
        self.add_flow_go_to_table_on_arp(
            datapath,
            self.CLASSIFIER_TABLE,
            NORMAL_PRIOREITY_FLOW,
            self.ARP_AND_BR_TABLE)
        self.add_flow_goto_table_on_broad(
            datapath,
            self.CLASSIFIER_TABLE,
            MEDIUM_PRIOREITY_FLOW,
            self.ARP_AND_BR_TABLE)
        self.add_flow_goto_table_on_mcast(
            datapath,
            self.CLASSIFIER_TABLE,
            NORMAL_PRIOREITY_FLOW,
            self.ARP_AND_BR_TABLE)

        # Normal flow on arp table in low priorety
        self.add_flow_normal(datapath, self.ARP_AND_BR_TABLE, 1)

    def send_port_desc_stats_request(self, datapath):
        ofp_parser = datapath.ofproto_parser

        req = ofp_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        ports = []
        datapath = ev.msg.datapath
        switch = self.dp_list.get(datapath.id)
        self.delete_all_flow_from_table(datapath, self.BASE_TABLE)
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

            if "tap" in port.name:
                LOG.debug(("Found DHCPD port  %s using MAC  %s"
                           "One machine install Special"
                           "(One Machine set up ) test use case"),
                          port.name,
                          port.hw_addr)
                self.add_flow_normal_by_port_num(
                    datapath, 0, HIGH_PRIOREITY_FLOW, port.port_no)
            elif "qvo" in port.name:
                # this is a VM port start with qvo<NET-ID[:11]> update the port
                # data with the port num and the switch dpid
                (port_id, mac, segmentation_id) = self.update_local_port_num(
                    port.name, port.port_no, datapath.id)
                self.add_flow_metadata_by_port_num(datapath,
                                                   0,
                                                   HIGH_PRIOREITY_FLOW,
                                                   port.port_no,
                                                   segmentation_id,
                                                   0xffff,
                                                   self.CLASSIFIER_TABLE)

                # vlan_id = self.get_l_vid_from_seg_id(switch, segmentation_id)
                LOG.debug(("Found VM  port  %s using MAC  %s  %d"),
                          port.name, port.hw_addr, datapath.id)
            elif "patch-tun" in port.name:
                LOG.debug(("Found br-tun patch port %s %s --> NORMAL path"),
                        port.name, port.hw_addr)
                switch.patch_port_num = port.port_no
                self.add_flow_normal_by_port_num(
                    datapath, 0, HIGH_PRIOREITY_FLOW, port.port_no)
        self.logger.debug('OFPPortDescStatsReply received: %s', ports)
        switch.local_ports = ports
        self.add_flow_go_to_table2(datapath, 0, 1, self.CLASSIFIER_TABLE)
        self.add_flow_match_to_controller(datapath, self.L3_VROUTER_TABLE, 0)
        self.add_flow_go_to_table2(datapath, self.CLASSIFIER_TABLE, 1,
                                   self.L3_VROUTER_TABLE)
        l3plugin = manager.NeutronManager.get_service_plugins().get(
            service_constants.L3_ROUTER_NAT)
        #TODO(gampel) Install flows only for tenants with VMs running on
        #this specific compute node
        for tenantid in self.tenants:
            for router in self.tenants[tenantid].routers:
                for subnet in router.subnets:
                    for interface in router.data['_interfaces']:
                        if (interface['subnet']['id'] == subnet.data['id']
                                and subnet.segmentation_id != 0):
                            segmentation_id = subnet.segmentation_id
                            network, net_mask = self.get_subnet_from_cidr(
                                subnet.data['cidr'])

                            self.add_flow_normal_local_subnet(
                                datapath,
                                self.L3_VROUTER_TABLE,
                                NORMAL_PRIOREITY_FLOW,
                                network,
                                net_mask,
                                segmentation_id)

                            self.add_flow_match_gw_mac_to_cont(
                                datapath,
                                interface['mac_address'],
                                self.L3_VROUTER_TABLE,
                                99,
                                segmentation_id)
                            l3plugin.setup_vrouter_arp_responder(
                                self.ctx,
                                "br-int",
                                "add",
                                self.ARP_AND_BR_TABLE,
                                segmentation_id,
                                interface['network_id'],
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
        self.logger.info("packet-out %s" % (pkt,))
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

    def update_local_port_num(self, port_name, port_num, dpid):

        for tenantid in self.tenants:
            tenant = self.tenants[tenantid]
            for mac in tenant.mac_to_port_data:
                port_data = tenant.mac_to_port_data[mac]
                # print "port_data >>>>>>>>>>>>>>%s",port_data
                if 'id' in port_data:
                    port_id = port_data['id']
                    sub_str_port_id = str(port_id[0:11])
                    port_id_from_name = port_name[3:]
                    if sub_str_port_id == port_id_from_name:
                        port_data['local_port_num'] = port_num
                        port_data['local_dpid_switch'] = dpid
                        return (
                            port_data['id'],
                            mac,
                            port_data['segmentation_id'])
                else:
                    LOG.error(("No data in port)data %s "), port_data)
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
                        LOG.info(("Sending ping echo -> ip %s "), pkt_ipv4.src)
                        retVal = 1
                    else:
                        LOG.error(("any comunication to a router that"
                                   " is not ping should be dropped from"
                                   "ip  %s",
                                   pkt_ipv4.src))
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
