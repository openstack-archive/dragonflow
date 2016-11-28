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

from dragonflow.db.migration import common

DESCRIPTION = "Initialize the Dragonflow Northbound Database migration."

OPENSTACK_VERSION = common.PIKE

DATE = "2017-08-23 00:00"


def upgrade(db_driver):
    """Check if the metadata of nb db is defined. If not, initialize it."""
    db_driver.create_table(common.METADATA_TABLE_NAME)
