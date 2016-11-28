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

import collections
import imp
import mock
import os

from dragonflow.db.migration import common as migration_common
from dragonflow.tests import base as tests_base


VersionMod = collections.namedtuple(
    'VersionMod', ('DESCRIPTION', 'OPENSTACK_VERSION', 'DATE', 'upgrade'))
date_regex = '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-5][0-9]:[0-5][0-9]$'


class DBMigrationTestCase(tests_base.BaseTestCase):

    def test_all_upgrade_modules(self):
        """This UT will make sure all upgrade modules are legal."""
        all_versions = migration_common.get_sorted_all_version_modules()
        # As the code written, the upgrade module should not be empty.
        self.assertTrue(all_versions)
        for mod in all_versions:
            self.assertTrue(mod.DESCRIPTION)
            self.assertTrue(mod.OPENSTACK_VERSION)
            self.assertTrue(mod.DATE)
            self.assertRegexpMatches(mod.DATE, date_regex)
            self.assertTrue(mod.upgrade)

    @mock.patch.object(os, 'listdir')
    @mock.patch.object(imp, 'load_source')
    def test_get_sorted_all_version_modules(self, load_source, listdir):
        listdir.return_value = ('_private1.py', 'mod1.py', 'mod2_ignore',
                                'mod3.py')

        def load_source_func(filename, path):
            if filename == 'mod1':
                return VersionMod('mod1', 'pike', '2017-08-23 00:00', None)

            elif filename == 'mod3':
                return VersionMod('mod3', 'pike', '2017-07-23 00:00', None)
            else:
                self.fail("Unexpected filename %s" % filename)
        load_source.side_effect = load_source_func
        all_versions = migration_common.get_sorted_all_version_modules()
        self.assertEqual('mod3', all_versions[0].DESCRIPTION)
        self.assertEqual('pike', all_versions[0].OPENSTACK_VERSION)
        self.assertEqual('2017-07-23 00:00', all_versions[0].DATE)

        self.assertEqual('mod1', all_versions[1].DESCRIPTION)
        self.assertEqual('pike', all_versions[1].OPENSTACK_VERSION)
        self.assertEqual('2017-08-23 00:00', all_versions[1].DATE)

    def test_get_current_db_date(self):
        db_driver = mock.Mock()
        db_driver.get_key.return_value = None
        self.assertIsNone(migration_common.get_current_db_date(db_driver))

        db_driver.get_key.return_value = ('{"date": "2017-08-23 00:00",' +
                                          ' "os_version": "pike",' +
                                          ' "description": "description"}')
        self.assertEqual("2017-08-23 00:00",
                         migration_common.get_current_db_date(db_driver))

    @mock.patch.object(migration_common, "get_sorted_all_version_modules")
    @mock.patch.object(migration_common, "set_db_migration_metadata")
    def test_set_db_version_to_latest(self, set_db_migration_metadata,
                                      get_sorted_all_version_modules):
        mod1 = VersionMod('mod1', 'pike', '2017-08-23 00:00', None)
        mod2 = VersionMod('mod1', 'pike', '2017-08-24 00:00', None)
        get_sorted_all_version_modules.return_value = (mod1, mod2)
        sentinel = mock.sentinel
        migration_common.set_db_version_to_latest(sentinel)
        set_db_migration_metadata.assert_called_once_with(sentinel, mod2)

    def test_set_db_migration_metadata(self):
        db_driver = mock.Mock()
        mod1 = VersionMod('mod1', 'pike', '2017-08-23 00:00', None)
        migration_common.set_db_migration_metadata(db_driver, mod1)
        db_driver.set_key.assert_called_once_with(
            migration_common.METADATA_TABLE_NAME,
            migration_common.MIGRATION_KEY,
            ('{"date": "2017-08-23 00:00",' +
             ' "os_version": "pike",' +
             ' "description": "mod1"}'))

    @mock.patch.object(migration_common, "set_db_migration_metadata")
    @mock.patch.object(migration_common, "get_sorted_all_version_modules")
    @mock.patch.object(migration_common, "get_current_db_date")
    def test_migrate_database(self, get_current_db_date,
                              get_sorted_all_version_modules,
                              set_db_migration_metadata):
        db_driver = mock.sentinel
        get_current_db_date.return_value = '2017-08-23 12:00'
        mod1 = VersionMod('mod1', 'pike', '2017-08-23 00:00', mock.Mock())
        mod2 = VersionMod('mod1', 'pike', '2017-08-23 12:00', mock.Mock())
        mod3 = VersionMod('mod1', 'pike', '2017-08-23 18:00', mock.Mock())
        mod4 = VersionMod('mod1', 'pike', '2017-08-23 23:00', mock.Mock())
        mods = (mod1, mod2, mod3, mod4)
        get_sorted_all_version_modules.return_value = mods
        migration_common.migrate_database(db_driver)
        mod1.upgrade.assert_not_called()
        mod2.upgrade.assert_not_called()
        mod3.upgrade.assert_called_once_with(db_driver)
        mod4.upgrade.assert_called_once_with(db_driver)
        for mod in mods:
            mod.upgrade.reset_mock()
        set_db_migration_metadata.assert_called_once_with(db_driver, mod4)
        set_db_migration_metadata.reset_mock()

        get_current_db_date.return_value = None
        mod1 = VersionMod('mod1', 'pike', '2017-08-23 00:00', mock.Mock())
        mod2 = VersionMod('mod1', 'pike', '2017-08-23 12:00', mock.Mock())
        mod3 = VersionMod('mod1', 'pike', '2017-08-23 18:00', mock.Mock())
        mod4 = VersionMod('mod1', 'pike', '2017-08-23 23:00', mock.Mock())
        mods = (mod1, mod2, mod3, mod4)
        get_sorted_all_version_modules.return_value = mods
        migration_common.migrate_database(db_driver)
        mod1.upgrade.assert_called_once_with(db_driver)
        mod2.upgrade.assert_called_once_with(db_driver)
        mod3.upgrade.assert_called_once_with(db_driver)
        mod4.upgrade.assert_called_once_with(db_driver)
        set_db_migration_metadata.assert_called_once_with(db_driver, mod4)
        set_db_migration_metadata.reset_mock()
