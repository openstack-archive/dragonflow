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
from dragonflow.db.models import l3


@migration.define_migration(
    id='dragonflow.core.queens.remove_name_from_floatingip',
    description='Remove name from floatingip',
    release=migration.QUEENS,
    proposed_at='2017-12-19 00:00:00',
    affected_models=[l3.FloatingIp]
)
def migration(nb_api):
    """
    The 'name' field is no longer part of FloatingIp.
    """
    db_driver = nb_api.db_driver
    keys = db_driver.get_all_keys(l3.FloatingIp.table_name)
    for key in keys:
        fip_json = db_driver.get_key(l3.FloatingIp.table_name, key)
        fip = jsonutils.loads(fip_json)
        fip.pop('name', None)
        fip_json = jsonutils.dumps(fip)
        db_driver.set_key(l3.FloatingIp.table_name, key, fip_json,
                          topic=fip['topic'])
