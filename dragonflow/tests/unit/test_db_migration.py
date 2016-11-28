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
import time

import testtools

from dragonflow.common import utils
from dragonflow.db import api_nb
from dragonflow.db import migration
from dragonflow.tests import base as tests_base
from dragonflow.tests.unit import migrations
from dragonflow.tests.unit.migrations import migration1
from dragonflow.tests.unit.migrations import migration2
from dragonflow.tests.unit import other_migrations
from dragonflow.tests.unit.other_migrations import migration3


def _upgrade(self, nb_api=None):
    time.sleep(0.2)


def _upgrade_with_error(self, nb_api=None):
    time.sleep(0.2)
    1 / 0


class TestExtensionManager(object):
    def __init__(self, *args, **kwargs):
        pass

    def __iter__(self):
        for mod in (migrations, other_migrations):
            yield mock.Mock(plugin=mod)


class DBMigrationTestCase(tests_base.BaseTestCase):
    def setUp(self):
        super(DBMigrationTestCase, self).setUp()
        self.driver = utils.load_driver(
                '_dummy_nb_db_driver',
                utils.DF_NB_DB_DRIVER_NAMESPACE)
        self.driver.initialize(None, None, config=None)
        self.nb_api = api_nb.NbApi(self.driver)
        self._M = [
            migration.SchemaMigration(
                id='migration1',
                description='description1',
                proposed_at='2017-09-01 00:00:00',
                release=migration.PIKE,
                upgrade_func=mock.Mock(side_effect=_upgrade),
            ),
            migration.SchemaMigration(
                id='migration2',
                description='description2',
                proposed_at='2017-09-12 00:00:00',
                release=migration.PIKE,
                upgrade_func=mock.Mock(side_effect=_upgrade),
            ),
            migration.SchemaMigration(
                id='migration3',
                description='description3',
                proposed_at='2017-09-03 00:00:00',
                release=migration.PIKE,
                upgrade_func=mock.Mock(side_effect=_upgrade),
            ),
            migration.SchemaMigration(
                id='migration4',
                description='description4',
                proposed_at='2017-09-02 00:00:00',
                release=migration.PIKE,
                upgrade_func=mock.Mock(side_effect=_upgrade),
            )
        ]

    def test_find_all_migrations(self):
        with mock.patch('stevedore.ExtensionManager', TestExtensionManager):
            found_migrations = tuple(migration.find_all_migrations())
            self.assertItemsEqual(
                (
                    migration1.migration.id,
                    migration2.migration.id,
                    migration3.migration.id,
                ),
                (m.id for m in found_migrations),
            )

    def test_apply_all_migrations(self):
        with mock.patch.object(migration, 'find_all_migrations',
                               return_value=self._M):
            migration.apply_new_migrations(self.nb_api)
            applied = self.nb_api.get_all(migration.SchemaMigration)
            applied = sorted(applied, key=lambda x: x.id)

            # Check all upgrade funcs were called
            for m in self._M:
                m._internal_apply.assert_called()

            # and all migrations are applied
            self.assertEqual(4, len(applied))

            # Successfully
            for m in applied:
                self.assertEqual('Success', m.status)

            # And in correct order
            self.assertLess(applied[0].applied_at, applied[3].applied_at)
            self.assertLess(applied[3].applied_at, applied[2].applied_at)
            self.assertLess(applied[2].applied_at, applied[1].applied_at)

    def test_apply_stops_on_error(self):
        with mock.patch.object(migration, 'find_all_migrations',
                               return_value=self._M):
            self._M[3]._internal_apply = mock.Mock(
                side_effect=_upgrade_with_error)

            with testtools.ExpectedException(ZeroDivisionError):
                migration.apply_new_migrations(self.nb_api)

            applied = self.nb_api.get_all(migration.SchemaMigration)
            applied = sorted(applied, key=lambda x: x.id)

            # Check first 2 upgrade funcs were called
            self._M[0]._internal_apply.assert_called()
            self._M[3]._internal_apply.assert_called()

            # and both migrations written in the database
            self.assertEqual(2, len(applied))
            self.assertLess(applied[0].applied_at, applied[1].applied_at)

    def test_apply_norun(self):
        with mock.patch.object(migration, 'find_all_migrations',
                               return_value=self._M):
            migration.mark_all_migrations_applied(self.nb_api)
            applied = self.nb_api.get_all(migration.SchemaMigration)
            applied = sorted(applied, key=lambda x: x.id)

            # Check no upgrade code was actually called
            for m in self._M:
                m._internal_apply.assert_not_called()

            # and all migrations appear in the database
            self.assertEqual(4, len(applied))
