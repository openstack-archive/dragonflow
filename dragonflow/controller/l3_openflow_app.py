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
import netaddr
import struct
import threading

import ryu
from ryu.base import app_manager
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.ofproto import ether
from ryu.ofproto import ofproto_v1_3

from ryu.lib.packet import arp
from ryu.lib.packet import ethernet
from ryu.lib.packet import packet

from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import icmp
from ryu.lib.packet import ipv4
from ryu.lib.packet import ipv6
from ryu.lib.packet import tcp
from ryu.lib.packet import udp

from ryu.lib import addrconv

from neutron import context

from neutron.common import constants as const
from neutron.i18n import _LE, _LI, _LW
from oslo_log import log

from dragonflow.utils.bloomfilter import BloomFilter
LOG = log.getLogger(__name__)

ETHERNET = ethernet.ethernet.__name__
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

REG_32BIT_ON_MASK = 0x80000000

HIGH_PRIORITY_FLOW = 1000
MEDIUM_PRIORITY_FLOW = 100
NORMAL_PRIORITY_FLOW = 10
LOW_PRIORITY_FLOW = 1
LOWEST_PRIORITY_FLOW = 0


CONTROLLER_L3_CONFIGURED_FLOW_PRIORITY = 50
ROUTER_INTERFACE_FLOW_PRIORITY = 40
LOCAL_SUBNET_TRAFFIC_FLOW_PRIORITY = 30
EAST_WEST_TRAFFIC_TO_CONTROLLER_FLOW_PRIORITY = 20
SNAT_RULES_PRIORITY_FLOW = 10


class CookieFilter(BloomFilter):
    """Bloom Filter in a cookie

    Useful and delicious!

    To get a valid int cookie:
     cf = CookieFilter(keys)
     cookie = cf.to_cookie()

    When adding a flow:
     OFPModFlow(..., cookie=cookie)

    When matching a flow (cookie can also just be 0xFFFFFFFF):
     OFPModFlow(..., cookie=cookie, cookie_mask=cookie)
    """
    def __init__(self, keys=()):
        super(CookieFilter, self).__init__(
            num_bytes=8,
            num_probes=2,
            iterable=keys,
        )

    def to_cookie(self):
        return CookieFilter._array_to_int64(self.array)

    @staticmethod
    def from_route(route):
        """Create a filter for a route

        :type route: list of PortData objects
        :rtype: CookieFilter
        """

        # TODO(saggi) memoize
        return CookieFilter(port.cookie_hash for port in route)

    @staticmethod
    def from_port_data(port_data):
        """Create a CookieFilter from a single PortData object

        :type port_data: PortData
        :rtype: CookieFilter
        """
        # TODO(saggi) memoize
        return CookieFilter((port_data.cookie_hash,))

    @staticmethod
    def _array_to_int64(array):
        """Converts bloom filter mask or state to int64

        Only works if array length is 8

        :param array: Array of a bloom filter or mask
        :return: The resulting array encoded as a signed int
        :rtype: int
        """
        assert(len(array) == 8)
        return struct.unpack("Q", str(array))[0]


class AgentDatapath(object):
    """Represents a forwarding element switch local state"""

    def __init__(self):
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
        self.mac_to_port_data = {}
        self.subnets = {}
        self.id = tenant_id

    def add_router(self, router):
        self.routers[router.id] = router

    def del_router(self, id):
        try:
            del self.routers[id]
        except KeyError:
            return -1

    def add_node(self, value):
        self.nodes.add(value)

    def del_node(self, value):
        self.nodes.remove(value)

    def add_edge(self, from_node, to_node, distance):
        self.edges[from_node].append(to_node)
        self.edges[to_node].append(from_node)
        self.distances[(from_node, to_node)] = distance

    def find_port_data_by_ip_address(self, ip_address):
        for port_data in self.mac_to_port_data.values():
            for fixed_ip in port_data.fixed_ips:
                if ip_address == fixed_ip['ip_address']:
                    return port_data, self.subnets[fixed_ip['subnet_id']]
        else:
            return 0, 0

    def find_port_data_by_local_name(self, local_port_name):
        """
        :param local_port_name: local name of the port on the switch
                                (eg. "qvo2dcdg-as")
        :type: local_port_name: str
        :return: A PortData object if one was found or None if no matching
                 object exists
        :type: PortData
        """

        name_prefix_len = 3
        partial_id = local_port_name[name_prefix_len:]
        for port_data in self.mac_to_port_data.values():
            if port_data.id.startswith(partial_id):
                return port_data
        else:
            return None

    def get_route(self, pkt):
        """Get a possible route the packet can take to reach it's destination

        The are no guarantees that the returned route is the fastest. Only that
        it's possible.

        Currently doesn't support extra routes.

        :param pkt: The packet to trace
        :return: A list of port_data objects if a route was found or None if no
                 route is available.
        """
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        in_port_data = self.mac_to_port_data.get(pkt_ethernet.src)
        out_port_data = self.mac_to_port_data.get(pkt_ethernet.dst)
        if in_port_data is None or out_port_data is None:
            LOG.error(
                _LE("No data for packet ports %(src_mac)s %(dst_mac)s"),
                {"src_mac": pkt_ethernet.src,
                 "dst_mac": pkt_ethernet.dst}
            )
            return None

        (dst_port_data, dst_subnet) = self.find_port_data_by_ip_address(
            pkt_ipv4.dst
        )
        if not dst_port_data:
            LOG.error(
                _LE("No data for destination port %(dst_ip)s"),
                {"dst_ip": pkt_ipv4.dst}
            )
            return None

        is_same_port = out_port_data.id == dst_port_data.id
        if is_same_port:
            return [in_port_data, out_port_data]

        # In order to hop the target has to be a router
        if not out_port_data.is_router_interface:
            LOG.error(
                _LE("The gateway port is not a router  %(dst_mac)s"),
                {"dst_mac": pkt_ethernet.dst}
            )
            return None

        gateway_router = self.routers.get(out_port_data.device_id)
        if gateway_router is None:
            return None

        if dst_subnet.id in gateway_router.subnets:
            # TODO(saggi) add second leg to route
            return [in_port_data, out_port_data, dst_port_data]

        # route not found
        return None

    @property
    def unused_subnets(self):
        unused_subnets = self.subnets.copy()
        for port in self.mac_to_port_data.values():
            for fixed_ip in port.fixed_ips:
                unused_subnets.pop(fixed_ip['subnet_id'], None)

            # Optimization, no need to keep filtering if it's empty
            if len(unused_subnets) == 0:
                break

        return unused_subnets.values()


class Router(object):

    def __init__(self, data):
        self.data = data
        self.subnets = []

    def add_subnet(self, subnet):
        self.subnets.append(subnet.id)

    def remove_subnet(self, subnet):
        self.subnets.remove(subnet.id)

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

    def set_data(self, data):
        self.data = data

    @property
    def id(self):
        try:
            return self.data['id']
        except TypeError:
            return -1

    @property
    def cidr(self):
        """Return the CIDR information for this subnet

        :return: CIDR information for subnet
        :rtype: netaddr.IPNetwork
        """
        return netaddr.IPNetwork(self.data['cidr'])

    @property
    def gateway_ip(self):
        return self.data.get('gateway_ip')

    def is_ipv4(self):
        try:
            return (netaddr.IPNetwork(self.cidr).ip).version == 4
        except TypeError:
            return False

    def __repr__(self):
        return ("<Subnet id='%s' cidr='%s' gateway_ip='%s' " +
                "segmentation_id='%s'>") % (
            self.id,
            self.cidr,
            self.gateway_ip,
            self.segmentation_id,
        )


class SnatBinding(object):

    def __init__(self, subnet, port):
        self.subnet_id = subnet
        self.sn_port = port
        self.segmentation_id = 0


class PortData(object):
    def __init__(self, port_data):
        self._port_data = port_data

    @property
    def is_router_interface(self):
        if self._port_data['device_owner'] in const.ROUTER_INTERFACE_OWNERS:
            return True
        else:
            return False

    @property
    def id(self):
        return self._port_data['id']

    @property
    def device_id(self):
        return self._port_data['device_id']

    @property
    def fixed_ips(self):
        try:
            return tuple(self._port_data.get('fixed_ips'))
        except KeyError:
            return tuple()

    @property
    def segmentation_id(self):
        return self._port_data['segmentation_id']

    @property
    def local_port_number(self):
        try:
            return self._port_data['switch_port_desc']['local_port_num']
        except KeyError:
            return -1

    @property
    def local_datapath_id(self):
        try:
            return self._port_data['switch_port_desc']['local_dpid_switch']
        except KeyError:
            return -1

    @property
    def mac_address(self):
        return self._port_data['mac_address']

    @property
    def cookie_hash(self):
        """Create an int64 to be used for ovs cookie needs.
        :return:
        :rtype: int
        """
        uuid_prefix = self.id.split('-', 1)[0]
        return int(uuid_prefix, 16)

    def get_subnet_from_ip_address(self, ip_address):
        for fixed_ip in self.fixed_ips:
            if ip_address == fixed_ip['ip_address']:
                return fixed_ip
        else:
            return None

    @property
    def is_gateway(self):
        for subnet in self._port_data['subnets']:
            for fixed_ip in self.fixed_ips:
                if subnet['id'] == fixed_ip['subnet_id']:
                    if subnet['gateway_ip'] == fixed_ip['ip_address']:
                        return True
        else:
            return False

    def __getitem__(self, item):
        return self._port_data.__getitem__(item)

    def __setitem__(self, key, value):
        return self._port_data.__setitem__(key, value)


class L3ReactiveApp(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    BASE_RPC_API_VERSION = '1.0'

    BASE_TABLE = 0
    CLASSIFIER_TABLE = 40
    METADATA_TABLE_ID = 50
    ARP_AND_BR_TABLE = 51
    L3_VROUTER_TABLE = 52
    L3_PUBLIC_TABLE = 53
    TUN_TRANSLATE_TABLE = 60

    def __init__(self, *args, **kwargs):
        super(L3ReactiveApp, self).__init__(*args, **kwargs)
        self.mac_to_port = {}

        self.ctx = context.get_admin_context()
        self.lock = threading.Lock()
        self._tenants = {}
        self.need_sync = True
        self.dp_list = {}
        self.snat_bindings = {}
        self.idle_timeout = kwargs['idle_timeout']
        self.hard_timeout = kwargs['hard_timeout']
        if ryu.version_info < (3, 24):
            LOG.warning(_LW("Current Ryu version is outdated %s,"
                    "please update to the latest stable"), ryu.version)

    def get_tenant_by_id(self, tenant_id):
        if tenant_id in self._tenants:
            return self._tenants[tenant_id]
        else:
            return self._tenants.setdefault(tenant_id,
                                            TenantTopology(tenant_id))

    def start(self):
        LOG.info(_LI("Starting Virtual L3 Reactive OpenFlow APP "))
        super(L3ReactiveApp, self).start()
        return 1

    def delete_router(self, router_id):
        for tenant in self._tenants.values():
            try:
                router = tenant.routers.pop(router_id)
            except KeyError:
                pass
            else:
                for interface in router.interfaces:
                    for subnet_info in interface['subnets']:
                        subnet = tenant.subnets[subnet_info['id']]
                        if subnet.segmentation_id == 0:
                            continue

                        if subnet.is_ipv4():
                            self._remove_vrouter_arp_responder_cast(
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
                if subnet.data is None:
                    subnet.set_data(subnet_info)

                router.add_subnet(subnet)
                if subnet.segmentation_id != 0:
                    self.subnet_added_binding_cast(subnet, interface)
                    self.bootstrap_network_classifiers(
                        subnet=subnet)

        # If previous definition of the router is known
        if router_old:
            # Handle removed subnets
            for interface in router_old.interfaces:
                for subnet_info in interface['subnets']:
                    subnet = subnets[subnet_info['id']]
                    if subnet.segmentation_id == 0:
                        continue

                    # if subnet was not deleted
                    if subnet.id in router.subnets:
                        continue

                    if subnet.is_ipv4():
                        self._remove_vrouter_arp_responder_cast(
                            subnet.segmentation_id,
                            interface['mac_address'],
                            self.get_ip_from_interface(interface))
                        if PortData(interface).is_gateway:
                            self._handle_remove_subnet(subnet)

                        self._handle_remove_port(PortData(interface))

    def _handle_remove_subnet(self, subnet):
        """Remove all the flow relating to a specific subnet

        :param subnet:
        :type subnet: Subnet
        """
        for dp in self.dp_list.values():
            datapath = dp.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match = parser.OFPMatch()
            match.set_dl_type(ether.ETH_TYPE_IP)
            match.set_ipv4_dst_masked(subnet.cidr.ip.value,
                                      subnet.cidr.netmask.value)
            msg = parser.OFPFlowMod(datapath=datapath,
                                    cookie=0,
                                    cookie_mask=0,
                                    table_id=L3ReactiveApp.L3_VROUTER_TABLE,
                                    command=ofproto.OFPFC_DELETE,
                                    priority=MEDIUM_PRIORITY_FLOW,
                                    out_port=ofproto.OFPP_ANY,
                                    out_group=ofproto.OFPG_ANY,
                                    match=match)
            datapath.send_msg(msg)
            match = parser.OFPMatch()
            match.set_dl_type(ether.ETH_TYPE_IP)
            match.set_metadata(subnet.segmentation_id)
            msg = parser.OFPFlowMod(datapath=datapath,
                                    cookie=0,
                                    cookie_mask=0,
                                    table_id=L3ReactiveApp.L3_VROUTER_TABLE,
                                    command=ofproto.OFPFC_DELETE,
                                    priority=MEDIUM_PRIORITY_FLOW,
                                    out_port=ofproto.OFPP_ANY,
                                    out_group=ofproto.OFPG_ANY,
                                    match=match)
            datapath.send_msg(msg)

    def attach_switch_port_desc_to_port_data(self, port_data):
        if 'id' in port_data:
            port_id = port_data['id']
            sub_str_port_id = str(port_id[0:11])

            # Only true if we already received port_desc from OVS
            for switch in self.dp_list.values():
                switch_port_desc_dict = switch.switch_port_desc_dict
                if sub_str_port_id in switch_port_desc_dict:
                    port_data['switch_port_desc'] = (
                        switch_port_desc_dict[sub_str_port_id])
                    port_desc = port_data['switch_port_desc']
                    self.add_flow_metadata_by_port_num(
                        port_desc['datapath'],
                        0,
                        HIGH_PRIORITY_FLOW,
                        port_desc['local_port_num'],
                        port_data['segmentation_id'],
                        0xffff,
                        self.CLASSIFIER_TABLE)

    def delete_port(self, port):
        """

        :param port:
        :type port: PortData
        """
        self._handle_remove_port(PortData(port))

    def _remove_flow_local_subnet(self, subnet):
        """

        :param subnet:
        :type subnet: Subnet
        """
        for dp in self.dp_list.values():
            datapath = dp.datapath
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match = parser.OFPMatch()
            match.set_dl_type(ether.ETH_TYPE_IP)
            match.set_metadata(subnet.segmentation_id)
            msg = parser.OFPFlowMod(datapath=datapath,
                                    cookie=0,
                                    cookie_mask=0,
                                    table_id=L3ReactiveApp.CLASSIFIER_TABLE,
                                    command=ofproto.OFPFC_DELETE,
                                    priority=MEDIUM_PRIORITY_FLOW,
                                    out_port=ofproto.OFPP_ANY,
                                    out_group=ofproto.OFPG_ANY,
                                    match=match)
            datapath.send_msg(msg)

    def _find_tenant_for_port_data(self, port_data):
        """

        :param port_data:
        :type port_data: PortData
        :return:
        :rtype: TenantTopology or None
        """

        for tenant in self._tenants.values():
            if port_data.mac_address in tenant.mac_to_port_data:
                return tenant
        else:
            return None

    def sync_port(self, port):
        LOG.info(_LI("sync_port--> %s\n"), port)
        segmentation_id = port.get('segmentation_id')
        if segmentation_id is None:
            LOG.info(_LI("no segmentation data in port --> %s"), port)
            return

        tenant_topo = self.get_tenant_by_id(port['tenant_id'])
        for subnet_dict in port.get('subnets', []):
            subnet = tenant_topo.subnets.get(subnet_dict['id'])
            if subnet:
                subnet.set_data(subnet_dict)
                subnet.segmentation_id = segmentation_id
            else:
                tenant_topo.subnets[subnet_dict['id']] = subnet = Subnet(
                    subnet_dict,
                    segmentation_id)
            if port['device_owner'] == const.DEVICE_OWNER_ROUTER_INTF:
                self.subnet_added_binding_cast(subnet, port)
                self.bootstrap_network_classifiers(subnet=subnet)
            self._add_flow_normal_local_subnet_cast(
                    LOCAL_SUBNET_TRAFFIC_FLOW_PRIORITY,
                    subnet)
        tenant_topo.mac_to_port_data[port['mac_address']] = PortData(port)
        self.attach_switch_port_desc_to_port_data(port)

    def get_port_subnets(self, port):
        subnets_ids = []
        if 'fixed_ips' in port:
            for fixed_ips in port['fixed_ips']:
                subnets_ids.append(fixed_ips['subnet_id'])
        return subnets_ids

    def _get_input_packet_handler(self, pkt):
        is_ipv4_packet = pkt.get_protocol(ipv4.ipv4) is not None
        is_ipv6_packet = pkt.get_protocol(ipv6.ipv6) is not None

        packet_handler = None
        if is_ipv4_packet:
            packet_handler = self.handle_ipv4_packet_in

        elif is_ipv6_packet:
            packet_handler = self.handle_ipv6_packet_in

        return packet_handler

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def OF_packet_in_handler(self, event):
        msg = event.msg
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

        pkt = packet.Packet(msg.data)
        packet_handler = self._get_input_packet_handler(pkt)
        if packet_handler is None:
            LOG.error(_LE("Unable to find appropriate packet "
                          "handler for packet: %s"), pkt)
        else:
            try:
                packet_handler(datapath, msg, pkt)
            except Exception as exception:
                LOG.debug(
                    "Unable to handle packet %(msg)s: %(e)s",
                    {'msg': msg, 'e': exception}
                )

    def handle_ipv6_packet_in(self, datapath, msg, pkt):
        # TODO(gampel)(gampel) add ipv6 support
        LOG.error(_LE("No handle for ipv6 yet should be offload to the"
                "NORMAL path  %s"), pkt)
        return

    def is_known_datapath(self, datapath):
        """Check if datapath is known to this openflow appliaction"""
        return self.dp_list.get(datapath.id) is not None

    def _handle_router_packet(self, datapath, pkt, route):
        """Handle packets intended for routers

        Specifically OAM (Operations, administration and management) packets
        Does nothing if pkt is not a supported protocol.

        The function assumes the route is valid and the packet is meant for the
        last port in the route.

        Currently only handles ping

        :param datapath: The datapath to send through
        :param pkt: The packet to handle
        :param route: The resolved route the packet is it take
        """
        is_icmp_packet = pkt.get_protocol(icmp.icmp) is not None

        if is_icmp_packet:
            # send ping response
            self._handle_icmp(
                datapath,
                pkt,
                route[0],
            )

        else:
            pkt_ipv4 = pkt.get_protocol(ipv4.ipv4) is not None
            LOG.error(_LE("any communication to a router that "
                          "is not ping should be dropped from "
                          "ip '%s'"),
                      pkt_ipv4.src)

    def _handle_vm_packet(self, datapath, msg, pkt, route):
        """Handle packets intended for VMs
        """
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)

        LOG.debug(
            "Installing flow Route %s-> %s",
            pkt_ipv4.src,
            pkt_ipv4.dst)

        self.install_l3_forwarding_flows(
            datapath,
            msg,
            route[0],
            pkt_ethernet,
            pkt_ipv4,
            route[1],
            route[-1],
            CookieFilter.from_route(route),
        )

    def _get_tenant_for_msg(self, msg, pkt):
        segmentation_id = msg.match.get('metadata')
        if segmentation_id is None:
            return None

        pkt_eth = pkt.get_protocol(ethernet.ethernet)
        for tenant in self._tenants.values():
            port_data = tenant.mac_to_port_data.get(pkt_eth)
            if port_data is None:
                # target is router
                for subnet in tenant.subnets.values():
                    if subnet.segmentation_id == segmentation_id:
                        return tenant
            else:
                for fixed_ip in port_data.fixed_ips:
                    subnet = tenant.subnets.get(fixed_ip['subnet_id'])
                    if subnet is None:
                        continue

                    if subnet.segmentation_id == segmentation_id:
                        return tenant

    def handle_ipv4_packet_in(self, datapath, msg, pkt):
        if not self.is_known_datapath(datapath):
            LOG.warning(_LW("Received packet from unknown datapath '%s'"),
                        datapath.id)
            return

        segmentation_id = msg.match.get('metadata')
        if segmentation_id is None:
            # send request for local switch data
            self.send_port_desc_stats_request(datapath)
            LOG.error(_LE("No metadata on packet from %s"),
                      pkt.get_protocol(ethernet.ethernet).src)
            return

        LOG.debug("packet segmentation_id %s ", segmentation_id)

        tenant = self._get_tenant_for_msg(msg, pkt)
        if tenant is None:
            LOG.warning(_LW("No available tenant for packet %s"),
                        pkt.get_protocol(ethernet.ethernet).src)

        route = tenant.get_route(pkt)
        if route is None:
            LOG.debug(
                "No route is available for packet %(src_ip)s->%(dst_ip)s",
                {"src_ip": pkt.get_protocol(ethernet.ethernet).src,
                 "dst_ip": pkt.get_protocol(ethernet.ethernet).dst})
            return

        final_port = route[-1]
        if final_port.is_router_interface:
            self._handle_router_packet(datapath, pkt, route)
        else:
            self._handle_vm_packet(datapath, msg, pkt, route)

    def install_l3_forwarding_flows(
            self,
            datapath,
            msg,
            in_port_data,
            pkt_eth,
            pkt_ipv4,
            gateway_port_data,
            dst_port_data,
            cookie_filter,
    ):
        """Install the l3 forwarding flows.

        :param datapath: Datapath to install into
        :param msg: Message to act upon
        :param in_port_data: The port that the message arrived in
        :type in_port_data: PortData
        :param pkt_eth: The ethernet part of the packet
        :param pkt_ipv4: The ipv4 part of the packet
        :param gateway_port_data: The gateway port through which the packet
                                 would have been routed
        :type gateway_port_data: PortData
        :param dst_port_data: The destination port.
        :type dst_port_data: PortData
        :param cookie_filter: The cookie to attach to all flows
        :type cookie_filter: CookieFilter
        """
        dst_port_dp_id = dst_port_data.local_datapath_id
        dst_seg_id = dst_port_data.segmentation_id
        in_port = in_port_data.local_port_number
        dst_port = dst_port_data.local_port_number
        src_seg_id = in_port_data.segmentation_id
        cookie = cookie_filter.to_cookie()

        if dst_port_dp_id == datapath.id:
            # The dst VM and the source VM are on the same compute Node
            # Send output flow directly to port, use the same datapath
            actions = self.add_flow_subnet_traffic(
                datapath,
                self.L3_VROUTER_TABLE,
                MEDIUM_PRIORITY_FLOW,
                in_port,
                src_seg_id,
                pkt_eth.src,
                pkt_eth.dst,
                pkt_ipv4.dst,
                pkt_ipv4.src,
                gateway_port_data.mac_address,
                dst_port_data.mac_address,
                dst_port,
                cookie=cookie,
            )
            # Install the reverse flow return traffic
            self.add_flow_subnet_traffic(
                datapath,
                self.L3_VROUTER_TABLE,
                MEDIUM_PRIORITY_FLOW,
                dst_port,
                dst_seg_id,
                dst_port_data.mac_address,
                gateway_port_data.mac_address,
                pkt_ipv4.src,
                pkt_ipv4.dst,
                pkt_eth.dst,
                in_port_data.mac_address,
                in_port,
                cookie=cookie,
            )
            self.handle_packet_out_l3(datapath, msg, dst_port, actions)
        else:
            # The dst VM and the source VM are NOT on the same compute node
            # Send output to br-tun patch port and install reverse flow on the
            # dst compute node
            remote_switch = self.dp_list.get(dst_port_dp_id)
            local_switch = self.dp_list.get(datapath.id)
            actions = self.add_flow_subnet_traffic(
                datapath,
                self.L3_VROUTER_TABLE,
                MEDIUM_PRIORITY_FLOW,
                in_port,
                src_seg_id,
                pkt_eth.src,
                pkt_eth.dst,
                pkt_ipv4.dst,
                pkt_ipv4.src,
                gateway_port_data.mac_address,
                dst_port_data.mac_address,
                local_switch.patch_port_num,
                dst_seg_id=dst_seg_id,
                cookie=cookie,
                dst_datapath=remote_switch.datapath,
            )

            # Remote reverse flow install
            self.add_flow_subnet_traffic(
                remote_switch.datapath,
                self.L3_VROUTER_TABLE,
                MEDIUM_PRIORITY_FLOW,
                dst_port,
                dst_seg_id,
                dst_port_data.mac_address,
                gateway_port_data.mac_address,
                pkt_ipv4.src,
                pkt_ipv4.dst,
                pkt_eth.dst,
                in_port_data.mac_address,
                remote_switch.patch_port_num,
                dst_seg_id=src_seg_id,
                cookie=cookie,
                dst_datapath=local_switch.datapath,
            )

            self.handle_packet_out_l3(remote_switch.datapath,
                    msg, dst_port, actions)

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
                                dst_mac, out_port_num, dst_seg_id=None,
                                cookie=0, dst_datapath=None):
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

        if dst_datapath:
            dst_ip_hex = self._get_dp_ip_as_int(dst_datapath)
            if ryu.version_info >= (3, 24):
                #register Action set is supported only in 3.24
                actions.append(parser.OFPActionSetField(reg7=dst_ip_hex))

        if dst_seg_id:
            # The dest vm is on another compute machine so we must set the
            # segmentation Id and set metadata for the tunnel bridge to
            # for this flow
            mask_dst_seg = int(dst_seg_id) | REG_32BIT_ON_MASK
            field = parser.OFPActionSetField(tunnel_id=mask_dst_seg)
            actions.append(field)
            goto_inst = parser.OFPInstructionGotoTable(
                    self.TUN_TRANSLATE_TABLE)
            inst.append(goto_inst)
        else:
            actions.append(parser.OFPActionOutput(out_port_num,
                                              ofproto.OFPCML_NO_BUFFER))
        inst.append(datapath.ofproto_parser.OFPInstructionActions(
                        ofproto.OFPIT_APPLY_ACTIONS, actions))
        self.mod_flow(
            datapath,
            cookie=cookie,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match,
            out_port=out_port_num,
            idle_timeout=self.idle_timeout,
            hard_timeout=self.hard_timeout)

        return actions

    def _add_flow_normal_local_subnet_cast(self, priority, subnet):
        if not subnet.is_ipv4():
            LOG.info(_LI("No support for IPV6"))
            return
        cidr = subnet.cidr
        for dp in self.dp_list.values():
            self.add_flow_normal_local_subnet(
                dp.datapath,
                self.CLASSIFIER_TABLE,
                priority,
                cidr.network.format(),
                str(cidr.prefixlen),
                subnet.segmentation_id)

    def add_flow_normal_local_subnet(self, datapath, table, priority,
                                     dst_net, dst_mask, seg_id):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(seg_id)
        match.set_ipv4_dst_masked(ipv4_text_to_int(str(dst_net)),
                                  mask_ntob(int(dst_mask)))
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_NORMAL)]
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
        actions = [parser.OFPActionOutput(ofproto.OFPP_NORMAL)]
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            datapath,
            inst=inst,
            table_id=table,
            priority=priority,
            match=match,
            flags=ofproto.OFPFF_SEND_FLOW_REM)

    def add_flow_metadata_by_port_num(self, datapath, table, priority,
                                      in_port, metadata,
                                      metadata_mask, goto_table):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
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
            match=match,
            flags=ofproto.OFPFF_SEND_FLOW_REM)

    def add_flow_normal(self, datapath, table, priority, match=None):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_NORMAL)]
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

    def add_flow_goto_normal_on_ipv6(self, datapath, table, priority):
        match = datapath.ofproto_parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IPV6)
        self.add_flow_normal(datapath, table, priority, match)

    def add_flow_goto_normal_on_broad(self, datapath, table, priority,
                                     goto_table_id):
        match = datapath.ofproto_parser.OFPMatch(eth_dst='ff:ff:ff:ff:ff:ff')
        self.add_flow_normal(datapath, table, priority, match)

    def add_flow_goto_normal_on_mcast(self, datapath, table, priority,
                                     goto_table_id):
        match = datapath.ofproto_parser.OFPMatch(eth_dst='01:00:00:00:00:00')
        addint = haddr_to_bin('01:00:00:00:00:00')
        match.set_dl_dst_masked(addint, addint)
        self.add_flow_normal(datapath, table, priority, match)

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

    def _handle_remove_port(self, port_data):
        """Broadcast remove commands to all datapaths

        :param port_data: port_data for the port that was removed
        :type port_data: PortData
        """
        owner_tenant = self._find_tenant_for_port_data(port_data)
        if owner_tenant is not None:
            owner_tenant.mac_to_port_data.pop(port_data.mac_address, None)
            for unused_subnet in owner_tenant.unused_subnets:
                self._remove_flow_local_subnet(unused_subnet)
                del owner_tenant.subnets[unused_subnet.id]

        cookie = CookieFilter.from_port_data(port_data).to_cookie()
        for datapath in self.dp_list.values():
            datapath = datapath.datapath
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto

            match = parser.OFPMatch()
            message = parser.OFPFlowMod(
                datapath=datapath,
                cookie=cookie,
                cookie_mask=cookie,
                table_id=L3ReactiveApp.L3_VROUTER_TABLE,
                command=ofproto.OFPFC_DELETE,
                priority=MEDIUM_PRIORITY_FLOW,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                match=match,
            )

            datapath.send_msg(message)

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
            if reason == ofproto.OFPPR_DELETE:
                for tenant in self._tenants.values():
                    port_data = tenant.find_port_data_by_local_name(
                        msg.desc.name)
                    if port_data is not None:
                        self._handle_remove_port(port_data)

    def add_bootstrap_flows(self, datapath):
        # Goto from main CLASSIFIER table
        self.add_flow_go_to_table2(datapath, 0, 1, self.CLASSIFIER_TABLE)

        #send L3 traffic unmatched to controller
        self.add_flow_go_to_table2(datapath, self.CLASSIFIER_TABLE, 1,
                                   self.L3_VROUTER_TABLE)

        # send L3 traffic that is not east west to public network
        self.add_flow_go_to_table2(datapath, self.L3_VROUTER_TABLE, 1,
                                   self.L3_PUBLIC_TABLE)

        # Update inner subnets and SNAT
        self.bootstrap_network_classifiers()

        #Goto from CLASSIFIER to ARP Table on ARP
        self.add_flow_go_to_table_on_arp(
            datapath,
            self.CLASSIFIER_TABLE,
            HIGH_PRIORITY_FLOW,
            self.ARP_AND_BR_TABLE)
        #Goto from CLASSIFIER to NORMAL on broadcast
        self.add_flow_goto_normal_on_broad(
            datapath,
            self.CLASSIFIER_TABLE,
            MEDIUM_PRIORITY_FLOW,
            self.ARP_AND_BR_TABLE)
        #Goto from CLASSIFIER to NORMAL on mcast
        self.add_flow_goto_normal_on_mcast(
            datapath,
            self.CLASSIFIER_TABLE,
            NORMAL_PRIORITY_FLOW,
            self.ARP_AND_BR_TABLE)
        #Goto from CLASSIFIER to NORMAL on IPV6 traffic
        self.add_flow_goto_normal_on_ipv6(
            datapath,
            self.CLASSIFIER_TABLE,
            NORMAL_PRIORITY_FLOW)

        # Normal flow on arp table in low priority
        self.add_flow_normal(datapath, self.ARP_AND_BR_TABLE, 1)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        switch = self.dp_list.get(datapath.id)
        if not switch:
            self.dp_list[datapath.id] = AgentDatapath()
        self.dp_list[datapath.id].datapath = datapath
        # Normal flow with the lowest priority to send all traffic to NORMAL
        # until the bootstrap is done
        self.add_flow_normal(datapath, self.BASE_TABLE, 0)
        self.send_port_desc_stats_request(datapath)

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofp = datapath.ofproto

        if msg.reason == ofp.OFPRR_DELETE:
            if msg.table_id == 0:
                self.send_port_desc_stats_request(datapath)

    def send_port_desc_stats_request(self, datapath):
        ofp_parser = datapath.ofproto_parser

        req = ofp_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.send_msg(req)

    def append_port_data_to_ports(self, ports_list, port):
        ports_list.append('port_no=%d hw_addr=%s name=%s config=0x%08x '
                          'state=0x%08x curr=0x%08x advertised=0x%08x '
                          'supported=0x%08x peer=0x%08x curr_speed=%d '
                          'max_speed=%d' %
                          (port.port_no, port.hw_addr,
                           port.name, port.config,
                           port.state, port.curr, port.advertised,
                           port.supported, port.peer, port.curr_speed,
                           port.max_speed))

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        ports = []
        datapath = ev.msg.datapath
        switch = self.dp_list.get(datapath.id)
        self.add_bootstrap_flows(datapath)
        for port in ev.msg.body:
            self.append_port_data_to_ports(ports, port)

            if port.name.startswith('tap'):
                LOG.debug(("Found DHCPD port  %s using MAC  %s"
                           "One machine install Special"
                           "(One Machine set up ) test use case"),
                          port.name,
                          port.hw_addr)
                self.add_flow_normal_by_port_num(
                    datapath, 0, HIGH_PRIORITY_FLOW, port.port_no)
            elif port.name.startswith('qvo') or port.name.startswith('qr'):
                # this is a VM/qrouter port start with qvo/qr<NET-ID[:11]>
                # update the port data with the port num and the switch dpid
                (port_id, mac, segmentation_id) = self.update_local_port_num(
                    port.name, port.port_no, datapath)
                if segmentation_id != 0:
                    self.add_flow_metadata_by_port_num(datapath,
                                                       0,
                                                       HIGH_PRIORITY_FLOW,
                                                       port.port_no,
                                                       segmentation_id,
                                                       0xffff,
                                                       self.CLASSIFIER_TABLE)
                LOG.debug("Found VM/router port %s using MAC  %s,"
                          " datapath: %d, port_no: %d, segmentation_id: %s",
                          port.name, port.hw_addr, datapath.id, port.port_no,
                          segmentation_id)
            elif "patch-tun" in port.name:
                LOG.debug("Found br-tun patch port %s %s --> NORMAL path",
                          port.name, port.hw_addr)
                switch.patch_port_num = port.port_no
                self.add_flow_normal_by_port_num(
                    datapath, 0, HIGH_PRIORITY_FLOW, port.port_no)
                if ryu.version_info >= (3, 24):
                    self._install_tunid_translation_to_mark(
                        datapath,
                        self.TUN_TRANSLATE_TABLE,
                        port.port_no,
                        LOW_PRIORITY_FLOW)
        LOG.debug('OFPPortDescStatsReply received: %s', ports)
        switch.local_ports = ports
        #TODO(gampel) Install flows only for tenants with VMs running on
        #this specific compute node
        for tenant in self._tenants.values():
            for router in tenant.routers.values():
                for subnet_id in router.subnets:
                    subnet = tenant.subnets[subnet_id]
                    for interface in router.data['_interfaces']:
                        for subnet_info in interface['subnets']:
                            if (subnet.data['id'] == subnet_info['id']
                                    and subnet.segmentation_id != 0):
                                self.add_subnet_binding(datapath,
                                        subnet,
                                        interface)

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
            for mac, port_data in tenant.mac_to_port_data.items():
                port_id = port_data.id
                sub_str_port_id = str(port_id[0:11])
                if sub_str_port_id == port_id_from_name:
                    port_data['switch_port_desc'] = switch_port_desc
                    return (
                        port_data['id'],
                        mac,
                        port_data['segmentation_id'])
        # This can happen if we received port description from OVS but didn't
        # yet received port_sync from the L3 service
        LOG.debug("Port data not found %s  num <%d> dpid <%d>", port_name,
                  port_num, dpid)
        return 0, 0, 0

    def get_ip_from_interface(self, interface):
        for fixed_ip in interface['fixed_ips']:
            if "ip_address" in fixed_ip:
                return fixed_ip['ip_address']

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

    def _handle_icmp(self, datapath, pkt, in_port):
        pkt_ethernet = pkt.get_protocol(ethernet.ethernet)
        pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
        pkt_icmp = pkt.get_protocol(icmp.icmp)

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
        self._send_packet(datapath, in_port.local_port_number, pkt)
        LOG.debug("Sending ping echo -> ip %s ", pkt_ipv4.src)

    def check_direct_routing(self, tenant, from_subnet_id, to_subnet_id):
        return

    def _get_dp_ip_as_int(self, datapath):
        try:
            return int(netaddr.IPAddress(datapath.address[0], version=4))
        except Exception:
            LOG.warn(_LW("Invalid remote IP: %s"), datapath.address)
            return

    def _get_match_vrouter_arp_responder(self, datapath, segmentation_id,
                                         interface_ip):
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_ARP)
        match.set_arp_tpa(ipv4_text_to_int(str(interface_ip)))
        match.set_arp_opcode(arp.ARP_REQUEST)
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
                   parser.OFPActionSetField(eth_src=mac_address),
                   parser.OFPActionSetField(arp_sha=mac_address),
                   parser.OFPActionSetField(arp_spa=interface_ip),
                   parser.OFPActionOutput(ofproto.OFPP_IN_PORT, 0)]
        instructions = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        return instructions

    def add_subnet_binding(self, datapath, subnet, interface):
        if not subnet.is_ipv4():
            LOG.info(_LI("No support for IPV6"))
            return
        self._add_vrouter_arp_responder(
                    datapath,
                    subnet.segmentation_id,
                    interface['mac_address'],
                    self.get_ip_from_interface(interface))

        cidr = subnet.cidr
        self.add_flow_normal_local_subnet(
            datapath,
            self.CLASSIFIER_TABLE,
            LOCAL_SUBNET_TRAFFIC_FLOW_PRIORITY,
            cidr.network.format(),
            str(cidr.prefixlen),
            subnet.segmentation_id)

    def subnet_added_binding_cast(self, subnet, interface):
        LOG.debug("adding %(segmentation_id)s, %(mac_address)s, "
                  "%(interface_ip)s",
                  {'segmentation_id': subnet.segmentation_id,
                   'mac_address': interface['mac_address'],
                   'interface_ip': self.get_ip_from_interface(interface)})
        for switch in self.dp_list.values():
            self.add_subnet_binding(switch.datapath, subnet, interface)

    def _add_vrouter_arp_responder(self, datapath, segmentation_id,
            mac_address, interface_ip):
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

    def _remove_vrouter_arp_responder_cast(self, segmentation_id, mac_address,
                                      interface_ip):
        LOG.debug("removing %(segmentation_id)s, %(mac_address)s, "
                  "%(interface_ip)s",
                  {'segmentation_id': segmentation_id,
                   'mac_address': mac_address,
                   'interface_ip': interface_ip})
        for switch in self.dp_list.values():
            datapath = switch.datapath
            self._remove_vrouter_arp_responder(
                    datapath,
                    segmentation_id,
                    mac_address,
                    interface_ip)

    def _remove_vrouter_arp_responder(self,
                                      datapath,
                                      segmentation_id,
                                      mac_address,
                                      interface_ip):
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

    def add_snat_binding(self, subnet_id, sn_port):
        snat_binding = SnatBinding(subnet_id, sn_port)
        self.snat_bindings[subnet_id] = snat_binding

        # Now find the segmentation ID for this subnet if it exists
        for tenantid in self._tenants:
            tenant = self._tenants[tenantid]
            for subnet in tenant.subnets.values():
                if subnet.id == subnet_id:
                    self.bootstrap_snat_subnet_flow(snat_binding, subnet)

    def remove_snat_binding(self, subnet_id):
        snat_binding = self.snat_bindings.get(subnet_id)

        if snat_binding is None:
            LOG.debug("subnet id %s not in snat_bindings", subnet_id)
            return

        for tenant in self._tenants.values():
            for subnet in tenant.subnets.values():
                if subnet.id == subnet_id:
                    self.remove_snat_binding_flows(snat_binding, subnet)

        del self.snat_bindings[subnet_id]

    def bootstrap_network_classifiers(self, subnet=None):
        if subnet is None:
            self.bootstrap_inner_subnets_connection()
            self.bootstrap_snat_flows()
        else:
            self.bootstrap_inner_subnets_connection_for_subnet(subnet)
            snat_binding = self.snat_bindings.get(subnet.id)
            if snat_binding is not None:
                self.bootstrap_snat_subnet_flow(snat_binding, subnet)

    def bootstrap_snat_subnet_flow(self, snat_binding, subnet):
        # TODO(gsagie) only iterate on DP's that implement the subnet
        for dp in self.dp_list.values():
            self.add_flow_snat_redirect(dp.datapath, snat_binding, subnet)

    def bootstrap_snat_flows(self):
        for tenant in self._tenants.values():
            for subnet in tenant.subnets.values():
                snat_binding = self.snat_bindings.get(subnet.id)
                if snat_binding is not None:
                    for dp in self.dp_list.values():
                        self.add_flow_snat_redirect(dp.datapath,
                                                    snat_binding, subnet)

    def remove_snat_binding_flows(self, snat_binding, subnet):
        # TODO(gsagie) only iterate on DP's that implement the subnet
        for dp in self.dp_list.values():
            self.remove_flow_snat_redirect(dp.datapath, snat_binding, subnet)

    def remove_flow_snat_redirect(self, datapath, snat_binding, subnet):
        if subnet.segmentation_id == 0:
            LOG.error(_LE("Segmentation id == 0 for subnet = %s"), subnet.id)
            return

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(subnet.segmentation_id)

        msg = parser.OFPFlowMod(datapath=datapath,
                                cookie=0,
                                cookie_mask=0,
                                table_id=self.L3_PUBLIC_TABLE,
                                command=ofproto.OFPFC_DELETE,
                                priority=SNAT_RULES_PRIORITY_FLOW,
                                out_port=ofproto.OFPP_ANY,
                                out_group=ofproto.OFPG_ANY,
                                match=match)
        datapath.send_msg(msg)

    def add_flow_snat_redirect(self, datapath, snat_binding, subnet):
        if not subnet.is_ipv4():
            LOG.info(_LI("No support for IPV6"))
            return

        if subnet.segmentation_id == 0:
            LOG.warning(_LW("Segmentation id == 0 for subnet = %s"), subnet.id)
            return

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(subnet.segmentation_id)

        eth_dst_mac = snat_binding.sn_port['mac_address']
        actions = [
            parser.OFPActionDecNwTtl(),
            parser.OFPActionSetField(eth_dst=eth_dst_mac),
            parser.OFPActionOutput(ofproto.OFPP_NORMAL),
        ]

        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            datapath,
            inst=inst,
            table_id=self.L3_PUBLIC_TABLE,
            priority=SNAT_RULES_PRIORITY_FLOW,
            match=match)

    def bootstrap_inner_subnets_connection_for_subnet(self, subnet):
        # First configure all flows from the subnet to all
        # the other possible subnets
        for dp in self.dp_list.values():
            self.bootstrap_inner_subnet_flows(dp.datapath, subnet)

        # For each other subnet, configure the opposite direction
        for tenant in self._tenants.values():
            for from_subnet in tenant.subnets.values():
                if (from_subnet.segmentation_id !=
                        subnet.segmentation_id):
                    for dp in self.dp_list.values():
                        self.add_flow_inner_subnet(dp.datapath,
                                                   from_subnet, subnet)

    def bootstrap_inner_subnets_connection(self):
        for tenant in self._tenants.values():
            for subnet in tenant.subnets.values():
                for dp in self.dp_list.values():
                    self.bootstrap_inner_subnet_flows(dp.datapath,
                                                      subnet)

    def bootstrap_inner_subnet_flows(self, datapath, from_subnet):
        for tenant in self._tenants.values():
            for to_subnet in tenant.subnets.values():
                if (to_subnet.segmentation_id !=
                        from_subnet.segmentation_id):
                    self.add_flow_inner_subnet(datapath,
                                            from_subnet, to_subnet)

    def add_flow_inner_subnet(self, datapath, from_subnet, to_subnet):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        if not (from_subnet.is_ipv4() and to_subnet.is_ipv4()):
            LOG.info(_LI("No support for IPV6"))
            return

        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        match.set_metadata(from_subnet.segmentation_id)

        match.set_ipv4_dst_masked(to_subnet.cidr.network.value,
                                  to_subnet.cidr.netmask.value)

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [datapath.ofproto_parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        self.mod_flow(
            datapath,
            inst=inst,
            table_id=self.L3_VROUTER_TABLE,
            priority=EAST_WEST_TRAFFIC_TO_CONTROLLER_FLOW_PRIORITY,
            match=match)

    def _install_tunid_translation_to_mark(self, datapath, table_id,
            port, priority=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        match.set_dl_type(ether.ETH_TYPE_IP)
        actions = [parser.NXActionRegMove(src_field='tunnel_id',
                                        dst_field='pkt_mark',
                                        n_bits=32),
                   parser.OFPActionOutput(port=port)]
        instructions = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        self.mod_flow(
            datapath,
            inst=instructions,
            table_id=table_id,
            priority=priority,
            match=match)

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
