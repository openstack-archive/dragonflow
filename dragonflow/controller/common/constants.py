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

# Pipline Table numbers
INGRESS_CLASSIFICATION_DISPATCH_TABLE = 0
EGRESS_PORT_SECURITY_TABLE = 1
EGRESS_CONNTRACK_TABLE = 3
EGRESS_SECURITY_GROUP_TABLE = 6
INGRESS_DESTINATION_PORT_LOOKUP_TABLE = 7
SERVICES_CLASSIFICATION_TABLE = 9
ARP_TABLE = 10
DHCP_TABLE = 11
METADATA_SERVICE_TABLE = 12
METADATA_SERVICE_REPLY_TABLE = 13
INGRESS_NAT_TABLE = 15
L2_LOOKUP_TABLE = 17
L3_LOOKUP_TABLE = 20
L3_PROACTIVE_LOOKUP_TABLE = 25
EGRESS_NAT_TABLE = 30
EGRESS_TABLE = 64
EGRESS_EXTERNAL_TABLE = 66
CANARY_TABLE = 200
# Pipeline Table numbers  Ingress
INGRESS_CONNTRACK_TABLE = 72
INGRESS_SECURITY_GROUP_TABLE = 77
INGRESS_DISPATCH_TABLE = 78

# Flow Priorities
PRIORITY_DEFAULT = 1
PRIORITY_VERY_LOW = 20
PRIORITY_LOW = 50
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


"""
Cookie Mask
global cookie is used by flows of all table, but local cookie is used
by flows of a small part of table. In order to avoid conflict,
global cookies should not overlapped with each other, but local cookies
could be overlapped for saving space of cookie.
all cookie's mask should be kept here to avoid conflict.
"""
GLOBAL_AGING_COOKIE_MASK = 0x1
SECURITY_GROUP_RULE_COOKIE_MASK = 0x1fffffffe
SECURITY_GROUP_RULE_COOKIE_SHIFT_LEN = 1
GLOBAL_INIT_AGING_COOKIE = 0x1

# These two globals are constant, as defined by the metadata service API. VMs
# contact 169.254.169.254:80, despite of where we actually listen to the
# service. This will be modified by flows.
METADATA_SERVICE_IP = '169.254.169.254'
HTTP_PORT = 80
