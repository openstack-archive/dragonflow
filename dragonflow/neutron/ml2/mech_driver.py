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

from neutron.common import constants as n_const
from neutron.extensions import portbindings
from neutron.plugins.ml2 import driver_api


class DFMechDriver(driver_api.MechanismDriver):

    """Dragonflow ML2 MechanismDriver for Neutron.

    """
    def initialize(self):
        self.vif_type = portbindings.VIF_TYPE_OVS
        # When set to True, Nova plugs the VIF directly into the ovs bridge
        # instead of using the hybrid mode.
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}

    def create_network_postcommit(self, context):
        pass
        # network = context.current
        # id = network['id']

    def update_network_postcommit(self, context):
        pass
        # network = context.current
        # name = network['name']

    def delete_network_postcommit(self, context):
        pass
        # network = context.current
        # id = network['id']

    def create_subnet_postcommit(self, context):
        pass

    def update_subnet_postcommit(self, context):
        pass

    def delete_subnet_postcommit(self, context):
        pass

    def _get_allowed_mac_addresses_from_port(self, port):
        allowed_macs = set()
        allowed_macs.add(port['mac_address'])
        allowed_address_pairs = port.get('allowed_address_pairs', [])
        for allowed_address in allowed_address_pairs:
            allowed_macs.add(allowed_address['mac_address'])
        return list(allowed_macs)

    def create_port_precommit(self, context):
        pass

    def create_port_postcommit(self, context):
        pass
        # port = context.current
        # id = port['id']
        # network = port['network_id']
        # mac = port['mac_address']

    def update_port_precommit(self, context):
        pass

    def update_port_postcommit(self, context):
        pass
        # port = context.current
        # id = port['id']
        # mac = port['mac_address']

    def delete_port_postcommit(self, context):
        pass
        # port = context.current
        # id = port['id']

    def bind_port(self, context):
        # This is just a temp solution so that Nova can boot images
        for segment in context.segments_to_bind:
            context.set_binding(segment[driver_api.ID],
                                self.vif_type,
                                self.vif_details,
                                status=n_const.PORT_STATUS_ACTIVE)
