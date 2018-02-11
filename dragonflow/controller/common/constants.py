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

# Pipeline Table numbers.
# In general each time packet is forwarded from one table to another
# as it goes in the pipeline, table id is increased.

# First table in the pipeline. All packets are landed here.
# In case packet is originated from local port, it is forwarded
# to EGRESS_PORT_SECURITY_TABLE.
# In case packet is coming from outside with a fip, it is
# forwarded to table INGRESS_NAT_TABLE for translation.
# In case the packet is coming with a tunnel id, it is
# translated to network id and the packet is forwarded to
# INGRESS_DESTINATION_PORT_LOOKUP_TABLE.
INGRESS_CLASSIFICATION_DISPATCH_TABLE = 0
# Detect reg6 (provider network and dNAT)
EXTERNAL_INGRESS_DETECT_SOURCE_TABLE = 2
# All packets from unknown ovs ports are dropped here. Other packets
# are forwarded to table EGRESS_CONNTRACK_TABLE.
EGRESS_PORT_SECURITY_TABLE = 5
# Next 2 tables are related to connection tracking and packet filtering.
# Used for SG.
EGRESS_CONNTRACK_TABLE = 10
EGRESS_SECURITY_GROUP_TABLE = 15
# Table is used to filter dhcp, arp, etc... packets.
SERVICES_CLASSIFICATION_TABLE = 20
# All ARP packets are landed here. ARP responses are generated.
ARP_TABLE = 25
# DHCP requests are forwarded to controller at this table.
DHCP_TABLE = 30
# Metadata service related tables.
METADATA_SERVICE_TABLE = 35
METADATA_SERVICE_REPLY_TABLE = 40
# ipv6 neighbor discovery table.
IPV6_ND_TABLE = 45
# Handle fip
INGRESS_NAT_TABLE = 50
INGRESS_SNAT_TABLE = 51
# Translate destination mac and port key to reg7 and forward packet to table
# L3_LOOKUP_TABLE. Duplicate broadcast packets.
L2_LOOKUP_TABLE = 55
# Filter packet based on destination IP address.
L3_LOOKUP_TABLE = 60
# Filter packet based on destination IP address in proactive way ;)
L3_PROACTIVE_LOOKUP_TABLE = 65
# Related to dnap app/snat_app
EGRESS_NAT_TABLE = 70
EGRESS_SNAT_TABLE = 71
# Depending on reg7, packet is pushed locally to EGRESS_EXTERNAL_TABLE or
# translated to tunnel.
EGRESS_TABLE = 75
# Table to handle FIP-to-VM DNAT traffic
INGRESS_DNAT_TABLE = 76
# Table to handle VM-to-FIP DNAT traffic
EGRESS_DNAT_TABLE = 77
# Push packet to local ovs port.
EGRESS_EXTERNAL_TABLE = 80
# All packets that come from remote host will go through this table
# and then go to INGRESS_CONNTRACK_TABLE. Broadcast packets are
# duplicated here.
INGRESS_DESTINATION_PORT_LOOKUP_TABLE = 100
# The next 2 tables are related to connection tracking and packet filtering.
# Used for SG.
CONNTRACK_PREPARE_TABLE = 105
INGRESS_CONNTRACK_TABLE = CONNTRACK_PREPARE_TABLE
CONNTRACK_TABLE = 106
CONNTRACK_RESULT_TABLE = 107
CONNTRACK_CLEANUP_TABLE = 108
EGRESS_SECURITY_GROUP_TABLE = 109
INGRESS_SECURITY_GROUP_TABLE = 110
# Send packets to target local ovs ports.
INGRESS_DISPATCH_TABLE = 115

# SFC tables
SFC_ENCAP_TABLE = 120
SFC_MPLS_DISPATCH_TABLE = 121
SFC_MPLS_PP_DECAP_TABLE = 122
SFC_END_OF_CHAIN_TABLE = 125

# Table used by aging app.
CANARY_TABLE = 200


# Flow Priorities
PRIORITY_DEFAULT = 1
PRIORITY_VERY_LOW = 20
PRIORITY_LOW = 50
PRIORITY_MEDIUM_LOW = 70
PRIORITY_MEDIUM = 100
PRIORITY_HIGH = 200
PRIORITY_VERY_HIGH = 300
PRIORITY_CT_STATE = 65534

# Connection Track flags
CT_STATE_NEW = 0x01
CT_STATE_EST = 0x02
CT_STATE_REL = 0x04
CT_STATE_RPL = 0x08
CT_STATE_INV = 0x10
CT_STATE_TRK = 0x20

CT_FLAG_COMMIT = 1

# Register match
METADATA_REG = 0x80000408
CT_ZONE_REG = 0x1d402

# Ports
MIN_PORT = 1
MAX_PORT = 65535
SG_TRACKING_ZONE = 65533
NAT_TRACKING_ZONE = 65534

# These two globals are constant, as defined by the metadata service API. VMs
# contact 169.254.169.254:80, despite of where we actually listen to the
# service. This will be modified by flows.
METADATA_SERVICE_IP = '169.254.169.254'
METADATA_HTTP_PORT = 80

DHCP_CLIENT_PORT = 68
DHCP_SERVER_PORT = 67
DHCPV6_CLIENT_PORT = 546
DHCPV6_SERVER_PORT = 547

EMPTY_MAC = '00:00:00:00:00:00'
BROADCAST_MAC = 'ff:ff:ff:ff:ff:ff'
BROADCAST_IP = '255.255.255.255'
CHASSIS_MAC_PREFIX = '91:92:'

CONTROLLER_SYNC = 'sync'
CONTROLLER_REINITIALIZE = 'reinitialize'
CONTROLLER_DBRESTART = 'dbrestart'
CONTROLLER_OVS_SYNC_STARTED = 'ovs_sync_started'
CONTROLLER_OVS_SYNC_FINISHED = 'ovs_sync_finished'
CONTROLLER_LOG = 'log'
