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

from oslo_log import log
from oslo_serialization import jsonutils

import dragonflow.db.migration.scripts


LOG = log.getLogger(__name__)
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

    mods.sort(key=lambda m: m.DATE)
    return mods


def get_current_db_date(db_driver):
    cur_version_json = db_driver.get_key(METADATA_TABLE_NAME,
                                         MIGRATION_KEY)
    if not cur_version_json:
        return None

    cur_version = jsonutils.loads(cur_version_json)
    return cur_version['date']


def set_db_version_to_latest(db_driver):
    all_versions = get_sorted_all_version_modules()
    latest = all_versions[-1]
    set_db_migration_metadata(db_driver, latest)


def set_db_migration_metadata(db_driver, ver_mod):
    ver_obj = {'description': ver_mod.DESCRIPTION,
               'date': ver_mod.DATE}
    db_driver.set_key(METADATA_TABLE_NAME, MIGRATION_KEY,
                      jsonutils.dumps(ver_obj))


def migrate_database(db_driver):
    cur_db_date = get_current_db_date(db_driver)
    all_versions = get_sorted_all_version_modules()
    if cur_db_date is None:
        all_relevant_versions = all_versions
    else:
        version_filter = lambda version: version.DATE > cur_db_date
        all_relevant_versions = list(filter(version_filter, all_versions))
    for version in all_relevant_versions:
        LOG.info("Upgrade to version %s: %s",
                 version.DATE, version.DESCRIPTION)
        version.upgrade(db_driver)

    set_db_migration_metadata(db_driver, all_relevant_versions[-1])
