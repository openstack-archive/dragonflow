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

import imp
import os

from datetime import datetime
from oslo_serialization import jsonutils

import dragonflow.db.migration.scripts
from dragonflow.db import models

OCATA = 'ocata'

METADATA_TABLE_NAME = "metadata"

MIGRATION_KEY = "migration"


def get_sorted_all_version_modules():
    """Return all nb db upgrade module objects in ascending order."""

    path = dragonflow.db.migration.scripts.__path__[0]
    mods = []
    for f in os.listdir(path):
        mod_name, file_ext = os.path.splitext(os.path.basename(f))
        mod_path = os.path.join(path, f)
        if file_ext.lower() == '.py' and not mod_name.startswith('_'):
            mod = imp.load_source(mod_name, mod_path)
            mods.append(mod)

    mods.sort(key=lambda m: m.VERSION)
    return mods


def get_current_db_version(db_driver):
    cur_version_json = db_driver.get_key(METADATA_TABLE_NAME,
                                         MIGRATION_KEY)
    if not cur_version_json:
        return None

    cur_version = jsonutils.loads(cur_version_json)
    return cur_version['version']


def set_db_migration_metadata(db_driver, ver_mod):
    date = datetime.strptime(ver_mod.DATE, '%Y-%m-%d %H:%M')

    ver_obj = {'version': ver_mod.VERSION,
               'description': ver_mod.DESCRIPTION,
               'os_version': ver_mod.OPENSTACK_VERSION,
               'date': str(date)}
    db_driver.set_key(METADATA_TABLE_NAME, MIGRATION_KEY,
                      jsonutils.dumps(ver_obj))


def ensure_unique_key(db_driver, nb_object):
    """Make sure the nb_object have an unique_key in it.

    For some old data that created before unique_key, this method can
    ensure there is no error when switching to new version.
    """
    if not isinstance(nb_object, models.NbDbObjectWithUniqueKey):
        return

    if nb_object.get_unique_key():
        return

    unique_key = db_driver.allocate_unique_key(nb_object.table_name)
    nb_object.inner_obj.update({models.UNIQUE_KEY: unique_key})
    nb_object_json = jsonutils.dumps(nb_object.inner_obj)
    db_driver.set_key(nb_object.table_name, nb_object.get_id(),
                      nb_object_json, nb_object.get_topic())
