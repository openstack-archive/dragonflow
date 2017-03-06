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

from dragonflow.db.models import l2
from dragonflow.neutron.common import constants as df_const


def logical_switch_from_neutron_network(network):
    return l2.LogicalSwitch(
        id=network['id'],
        topic=network['tenant_id'],
        name=network.get('name', df_const.DF_NETWORK_DEFAULT_NAME),
        network_type=network.get('provider:network_type'),
        physical_network=network.get('provider:physical_network'),
        segmentation_id=network.get('provider:segmentation_id'),
        router_external=network['router:external'],
        mtu=network.get('mtu'),
        version=network['revision_number'],
        qos_policy=network.get('qos_policy_id'))


def subnet_from_neutron_subnet(subnet):
    return l2.Subnet(
        id=subnet['id'],
        topic=subnet['tenant_id'],
        name=subnet.get('name', df_const.DF_SUBNET_DEFAULT_NAME),
        enable_dhcp=subnet['enable_dhcp'],
        cidr=subnet['cidr'],
        gateway_ip=subnet['gateway_ip'],
        dns_nameservers=[{'addr': nameserver} for nameserver in
                         subnet.get('dns_nameservers', [])],
        host_routes=subnet.get('host_routes', []))
