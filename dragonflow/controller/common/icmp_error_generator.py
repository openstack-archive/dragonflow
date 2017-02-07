# Copyright (c) 2017 Huawei Tech. Co., Ltd. .
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

from ryu.lib.packet import ethernet
from ryu.lib.packet import icmp
from ryu.lib.packet import ipv4
from ryu.lib.packet import packet
from ryu.ofproto import inet


def generate(icmp_type, icmp_code, msg_data, src_ip=None, pkt=None):
    """Generate ICMP error message

    :param icmp_type: The icmp type of packet
    :param icmp_code: The icmp code of packet
    :param msg_data: The original data that cause this ICMP error packet
    :param src_ip: The source ip of the packet
    :param pkt: The original packet that cause this ICMP error
    :returns: An ryu.lib.packet.packet.Packet instance, which is an ICMP packet
    """
    if not pkt:
        pkt = packet.Packet(msg_data)

    e_pkt = pkt.get_protocol(ethernet.ethernet)
    ipv4_pkt = pkt.get_protocol(ipv4.ipv4)
    if not src_ip:
        src_ip = ipv4_pkt.dst

    # Create ICMP data
    offset = ethernet.ethernet._MIN_LEN
    # Copy 128 bytes data according to RFC 4884
    end_of_data = offset + len(ipv4_pkt) + 128
    ip_datagram = bytearray()
    ip_datagram += msg_data[offset:end_of_data]
    data_len = int(len(ip_datagram) / 4)
    length_modulus = int(len(ip_datagram) % 4)
    # Zero pad to the next 32 bit boundary, according to RFC 4884
    if length_modulus:
        data_len += 1
        ip_datagram += bytearray([0] * (4 - length_modulus))
    # The only possibility now.
    icmp_data = icmp.TimeExceeded(data_len=data_len,
                                  data=ip_datagram)
    ic_pkt = icmp.icmp(icmp_type, icmp_code, 0, data=icmp_data)

    # Create IPv4 data
    ip_total_length = ipv4_pkt.header_length * 4 + ic_pkt._MIN_LEN
    ip_total_length += ic_pkt.data._MIN_LEN
    ip_total_length += len(ic_pkt.data.data)
    ipv4_pkt.total_length = ip_total_length
    # Default ttl
    ipv4_pkt.ttl = 64
    ipv4_pkt.proto = inet.IPPROTO_ICMP
    ipv4_pkt.csum = 0
    ipv4_pkt.src, ipv4_pkt.dst = src_ip, ipv4_pkt.src

    # Create ethernet data
    e_pkt.src, e_pkt.dst = e_pkt.dst, e_pkt.src

    pkt_reply = packet.Packet()
    pkt_reply.add_protocol(e_pkt)
    pkt_reply.add_protocol(ipv4_pkt)
    pkt_reply.add_protocol(ic_pkt)
    return pkt_reply
