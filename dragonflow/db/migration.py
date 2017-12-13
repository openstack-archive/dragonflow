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
import contextlib
import datetime
import pkgutil

from jsonmodels import fields
from oslo_log import log
import six
import stevedore

from dragonflow.common import utils
from dragonflow.db import api_nb
from dragonflow.db import db_common
from dragonflow.db import model_framework


LOG = log.getLogger(__name__)
PIKE = 'pike'
QUEENS = 'queens'
DRAGONFLOW_MIGRATIONS_NAMESPACE = 'dragonflow.db.migrations'


def _copy_all_tables(src, dst):
    for table in tuple(model_framework.iter_tables()) + (
        db_common.UNIQUE_KEY_TABLE,
    ):
        _copy_table(src, dst, table)


def _copy_table(src, dst, table):
    dst.delete_table(table)
    dst.create_table(table)

    for key in src.get_all_keys(table):
        dst.create_key(
            table,
            key,
            src.get_key(table, key),
        )


@contextlib.contextmanager
def _transactional_nb_api(nb_api):
    # FIXME (dimak): move out of testing
    dummy_driver = utils.load_driver(
            '_dummy_nb_db_driver',
            utils.DF_NB_DB_DRIVER_NAMESPACE)
    dummy_driver.initialize(None, None, config=None)
    dummy_nb_api = api_nb.NbApi(dummy_driver)

    _copy_all_tables(nb_api.driver, dummy_driver)

    yield dummy_nb_api
    _copy_all_tables(dummy_driver, nb_api.driver)


@model_framework.register_model
@model_framework.construct_nb_db_model
class SchemaMigration(model_framework.ModelBase):
    table_name = 'schema_migration'

    description = fields.StringField(required=True)
    release = fields.StringField(required=True)
    proposed_at = fields.DateTimeField(required=True)
    applied_at = fields.DateTimeField()

    def __init__(self, upgrade_func=None, **kwargs):
        super(SchemaMigration, self).__init__(**kwargs)
        self._internal_apply = upgrade_func

    def on_create_pre(self):
        self.applied_at = datetime.datetime.now()

    def apply(self, nb_api):
        LOG.info('Applying update %s', self.id)
        self._internal_apply(nb_api)


def define_migration(affected_models, **kwargs):
    def decorator(func):
        return SchemaMigration(
            upgrade_func=func,
            **kwargs
        )
    return decorator


def _get_applied_migrations(nb_api):
    return nb_api.get_all(SchemaMigration)


def apply_new_migrations(nb_api):
    applied_migrations = set(m.id for m in _get_applied_migrations(nb_api))
    all_migrations = find_all_migrations()
    new_migrations = [
        m for m in all_migrations if m.id not in applied_migrations
    ]

    if not new_migrations:
        return

    with _transactional_nb_api(nb_api) as t_nb_api:
        for migration in sorted(new_migrations, key=lambda m: m.proposed_at):
            migration.apply(t_nb_api)
            t_nb_api.create(migration)


def mark_all_migrations_applied(nb_api):
    for migration in find_all_migrations():
        nb_api.create(migration)


def find_all_migrations():
    for module in _get_all_migration_modules():
        migration = getattr(module, 'migration', None)
        if migration is not None:
            yield migration


def _get_all_migration_modules():
    for entry in _get_all_migration_entries():
        for (importer, name, ispkg) in pkgutil.iter_modules(entry.__path__):
            if ispkg:
                continue

            loader = importer.find_module(name)

            if six.PY3:
                yield loader.load_module(None)
            else:
                full_name = '{0}.{1}'.format(entry.__name__, name)
                yield loader.load_module(full_name)


def _get_all_migration_entries():
    for ext in stevedore.ExtensionManager(
        DRAGONFLOW_MIGRATIONS_NAMESPACE,
        invoke_on_load=False,
    ):
        yield ext.plugin
