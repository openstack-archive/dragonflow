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
from dragonflow.tests import base as tests_base


class DBMigrationTestCase(tests_base.BaseTestCase):

    def test_all_upgrade_modules(self):
        """This UT will make sure all upgrade modules are legal."""
        all_versions = migration_common.get_sorted_all_version_modules()
        # As the code written, the upgrade module should not be empty.
        self.assertTrue(all_versions)
        expected_version = 0
        for mod in all_versions:
            self.assertEqual(expected_version, mod.VERSION)
            expected_version += 1
            self.assertTrue(mod.DESCRIPTION)
            self.assertTrue(mod.OPENSTACK_VERSION)
            self.assertTrue(mod.DATE)
            self.assertTrue(mod.upgrade)
