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

from dragonflow.db.models import l3
from dragonflow.neutron.common import constants as df_const


def logical_router_from_neutron_router(router):
    return l3.LogicalRouter(
        id=router['id'],
        topic=router['tenant_id'],
        name=router.get('name', df_const.DF_ROUTER_DEFAULT_NAME),
        version=router['revision_number'],
        routes=router.get('routes', []))


def build_logical_router_port(router_port_info, mac, network, unique_key):
    return l3.LogicalRouterPort(
        id=router_port_info['port_id'],
        topic=router_port_info['tenant_id'],
        lswitch=router_port_info['network_id'],
        mac=mac,
        network=network,
        unique_key=unique_key)
