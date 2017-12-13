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

from oslo_serialization import jsonutils

from dragonflow.db import migration
from dragonflow.db.models import l2


@migration.define_migration(
    id='dragonflow.core.queens.make_subnet_a_first_order_model',
    description='Make Subnet a first order model',
    release=migration.QUEENS,
    proposed_at='2017-12-13 00:00:00',
    affected_models=[l2.LogicalNetwork, l2.Subnet]
)
def migration(nb_api):
    """
    Subnet is no longer embedded in LogicalNetwork. It is a first-order model.
    """
    db_driver = nb_api.db_driver
    keys = db_driver.get_all_keys(l2.LogicalNetwork.table_name)
    for key in keys:
        network_json = db_driver.get_key(l2.LogicalNetwork.table_name, key)
        network = jsonutils.loads(network_json)
        subnets = network.pop('subnets')
        for subnet in subnets:
            subnet['lswitch'] = network['id']
            subnet['version'] = 1
            subnet_json = jsonutils.dumps(subnet)
            db_driver.set_key(l2.Subnet.table_name, key, subnet_json,
                              topic=subnet['topic'])
        network_json = jsonutils.dumps(network)
        db_driver.set_key(l2.LogicalNetwork.table_name, key, network_json,
                          topic=network['topic'])
