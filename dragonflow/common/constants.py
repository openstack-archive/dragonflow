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
from neutron_lib import constants as n_const

OVS_VM_INTERFACE = "vm"
OVS_BRIDGE_INTERFACE = "bridge"
OVS_PATCH_INTERFACE = "patch"
OVS_TUNNEL_INTERFACE = "tunnel"
OVS_UNKNOWN_INTERFACE = "unknown"

DHCP_SIADDR = "siaddr"

DEVICE_OWNER_LOCAL_GW = (
            n_const.DEVICE_OWNER_NETWORK_PREFIX + "local_router_gateway")

DATA_DEVICE_OWNER = [
    n_const.DEVICE_OWNER_COMPUTE_PREFIX
]
