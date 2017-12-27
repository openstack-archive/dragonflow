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
from dragonflow.db.models import ovs


@migration.define_migration(
    id='dragonflow.core.queens.remove_peer_bridge_from_ovsport',
    description='Remove peer_bridge from OvsPort',
    release=migration.QUEENS,
    proposed_at='2017-12-27 00:00:00',
    affected_models=[ovs.OvsPort]
)
def migration(nb_api):
    """
    The 'peer_bridge' field is no longer part of OvsPort.
    """
    db_driver = nb_api.db_driver
    keys = db_driver.get_all_keys(ovs.OvsPort.table_name)
    for key in keys:
        ovsport_json = db_driver.get_key(ovs.OvsPort.table_name, key)
        ovsport = jsonutils.loads(ovsport_json)
        ovsport.pop('peer_bridge', None)
        ovsport_json = jsonutils.dumps(ovsport)
        db_driver.set_key(ovs.OvsPort.table_name, key, ovsport_json)
