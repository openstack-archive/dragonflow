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
SERVICES_CLASSIFICATION_TABLE = 9
ARP_TABLE = 10
DHCP_TABLE = 11
L2_LOOKUP_TABLE = 17
L3_LOOKUP_TABLE = 20
L3_PROACTIVE_LOOKUP_TABLE = 25
EGRESS_TABLE = 64

# Flow Priorities
PRIORITY_DEFAULT = 1
PRIORITY_LOW = 50
PRIORITY_MEDIUM = 100
PRIORITY_HIGH = 200
PRIORITY_VERY_HIGH = 300
CANARY_TABLE = 200

# Cookie Mask
# there are two types of cookies: global cookie and local cookie,
# global cookies should not swapped with local cookies, global cookies
# should not swapped with global cookies, but local cookies could not
# swapped with local cookies
GLOBAL_AGING_COOKIE_MASK = 0x1
LOCAL_TUNNEL_KEY_COOKIE = 0x1fffffffe
LOCAL_TUNNEL_KEY_SHIFT_LEN = 1
GLOBAL_INIT_AGING_COOKIE = 0x0
