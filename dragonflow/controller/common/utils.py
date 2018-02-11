# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import struct

import netaddr
from neutron_lib import constants as n_const
from oslo_log import log
from ryu.lib import addrconv
from ryu.ofproto import ether

from dragonflow.common import exceptions

LOG = log.getLogger(__name__)


def ipv4_text_to_int(ip_text):
    try:
        return struct.unpack('!I', addrconv.ipv4.text_to_bin(ip_text))[0]
    except Exception:
        raise exceptions.InvalidIPAddressException(key=ip_text)


def ipv6_text_to_short(ip_text):
    try:
        return list(struct.unpack('!8H', addrconv.ipv6.text_to_bin(ip_text)))
    except Exception:
        raise exceptions.InvalidIPAddressException(key=ip_text)


def ethertype_to_ip_version(ethertype):
    if ethertype == n_const.IPv4:
        return n_const.IP_VERSION_4
    if ethertype == n_const.IPv6:
        return n_const.IP_VERSION_6
    raise exceptions.InvalidEtherTypeException(ethertype=ethertype)


def get_eth_from_ip_version(ip_version):
    """
    Returns the eth_type that should be matched to the received ip

    :param ip_version: IP version int in the format 4/6
    """
    match_items = {
        (n_const.IP_VERSION_4): ether.ETH_TYPE_IP,
        (n_const.IP_VERSION_6): ether.ETH_TYPE_IPV6
    }
    return match_items[ip_version]


def get_port_match_list_from_port_range(port_range_min, port_range_max):
    port_range = netaddr.IPRange(port_range_min, port_range_max)
    ports_match_list = []
    for cidr in port_range.cidrs():
        port_num = int(cidr.network) & 0xffff
        mask = int(cidr.netmask) & 0xffff
        ports_match_list.append((port_num, mask))
    return ports_match_list
