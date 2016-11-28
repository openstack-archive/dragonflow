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

import datetime
import pkgutil

from jsonmodels import fields
from oslo_log import log
import six
import stevedore

from dragonflow.db import model_framework


LOG = log.getLogger(__name__)
PIKE = 'pike'
MIGRATION_KEY = "migration"


@model_framework.register_model
@model_framework.construct_nb_db_model
class SchemaMigration(model_framework.ModelBase):
    table_name = 'schema_migration'

    description = fields.StringField(required=True)
    release = fields.StringField(required=True)
    proposed_at = fields.DateTimeField(required=True)
    applied_at = fields.DateTimeField()
    status = fields.StringField()

    def __init__(self, upgrade_func=None, **kwargs):
        super(SchemaMigration, self).__init__(**kwargs)
        self._internal_apply = upgrade_func

    def on_create_pre(self):
        self.applied_at = datetime.datetime.now()

    def apply(self, nb_api):
        try:
            self._internal_apply(nb_api)
        except Exception as e:
            self.status = 'Failed with {err}'.format(err=str(e))
            raise
        else:
            self.status = 'Success'
        finally:
            nb_api.create(self)

    def apply_norun(self, nb_api):
        self.status = 'Marked as applied'
        nb_api.create(self)


def define_migration(**kwargs):
    def decorator(func):
        return SchemaMigration(
            upgrade_func=func,
            **kwargs
        )
    return decorator


def apply_new_migrations(nb_api):
    applied_migrations = set(m.id for m in nb_api.get_all(SchemaMigration))
    all_migrations = find_all_migrations()

    for migration in sorted(all_migrations, key=lambda m: m.proposed_at):
        if migration.id in applied_migrations:
            continue
        migration.apply(nb_api)


def mark_all_migrations_applied(nb_api):
    for migration in find_all_migrations():
        migration.apply_norun(nb_api)


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
        'dragonflow.db.migrations',
        invoke_on_load=False,
    ):
        yield ext.plugin
