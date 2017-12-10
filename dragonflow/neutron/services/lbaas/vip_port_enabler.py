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

from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import constants

LBAAS_PORT_OWNERS = [
    constants.DEVICE_OWNER_LOADBALANCER,
    constants.DEVICE_OWNER_LOADBALANCERV2,
]

try:
    from octavia.network.drivers.neutron import allowed_address_pairs
    LBAAS_PORT_OWNERS.append(allowed_address_pairs.OCTAVIA_OWNER)
except ImportError:
    pass  # No octavia


@registry.has_registry_receivers
class DfLBaaSVIPPortEnabler(object):
    @registry.receives(resources.PORT, [events.BEFORE_CREATE])
    def port_create(self, *args, **kwargs):
        port = kwargs['port']
        if port['device_owner'] not in LBAAS_PORT_OWNERS:
            return
        port['admin_state_up'] = True
