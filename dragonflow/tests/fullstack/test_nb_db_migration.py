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

import mock

from dragonflow.db.migration import common as migration_common
from dragonflow.db.migration.scripts import lswitch_unique_key
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.unit import test_app_base


class TestNbDbMigration(test_base.DFTestBase):

    def test_latest_version(self):
        all_versions = migration_common.get_sorted_all_version_modules()
        cur_ver_num = migration_common.get_current_db_version(
            self.nb_api.driver)
        # We expect the fullstack env will have the latest db version.
        self.assertEqual(all_versions[-1].VERSION, cur_ver_num)

    def test_migrate_lswitch_unique_key(self):
        fake_lswitch = test_app_base.fake_logic_switch1.inner_obj
        self.nb_api.create_lswitch(**fake_lswitch)
        self.addCleanup(self.nb_api.delete_lswitch,
                        fake_lswitch['id'], fake_lswitch['topic'])

        self.nb_api.update_lswitch(fake_lswitch['id'], fake_lswitch['topic'],
                                   unique_key=None)
        lswitch = self.nb_api.get_lswitch(fake_lswitch['id'],
                                          fake_lswitch['topic'])
        # Add a lswitch without unique_key in nb db
        self.assertIsNone(lswitch.get_unique_key())

        with mock.patch.object(migration_common, 'get_current_db_version',
                               return_value=lswitch_unique_key.VERSION - 1):
            lswitch_unique_key.upgrade(self.nb_api.driver)

        lswitch = self.nb_api.get_lswitch(fake_lswitch['id'],
                                          fake_lswitch['topic'])
        # Unique key has been added to lswitch in nb db
        self.assertIsNotNone(lswitch.get_unique_key())
