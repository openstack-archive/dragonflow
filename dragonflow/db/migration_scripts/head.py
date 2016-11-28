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

from dragonflow.db import migration


@migration.define_migration(
    id='dragonflow.core.pike.head',
    description='Initialize the Dragonflow Northbound Database migration.',
    release=migration.PIKE,
    proposed_at='2017-09-17 00:00:00',
)
def migration(nb_api):
    """Bootstrap migration mechanism by creating the table"""
    nb_api.db_driver.create_table(migration.Migration.table_name)
