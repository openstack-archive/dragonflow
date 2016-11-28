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

from dragonflow.db.migration import common as migration_common
from dragonflow.tests.fullstack import test_base


class TestNbDbMigration(test_base.DFTestBase):

    def test_latest_version(self):
        all_versions = migration_common.get_sorted_all_version_modules()
        cur_date = migration_common.get_current_db_date(self.nb_api.driver)
        # We expect the fullstack env will have the latest db date.
        self.assertEqual(all_versions[-1].DATE, cur_date)
