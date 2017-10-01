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
import threading

from oslo_log import log

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import db_api
from dragonflow.db import db_common


LOG = log.getLogger(__name__)


class _DummyDbDriver(db_api.DbApi):
    def __init__(self):
        super(_DummyDbDriver, self).__init__()
        self._db = collections.defaultdict(dict)
        self._unique_keys_lock = threading.Lock()

    def initialize(self, db_ip, db_port, **args):
        # Do nothing. Initialized automatically in construction
        pass

    def create_table(self, table):
        # Do nothing. Database is defaultdict
        pass

    def delete_table(self, table):
        self._db.pop(table, None)

    def get_key(self, table, key, topic=None):
        try:
            table_dict = self._db[table]
            return table_dict[key]
        except KeyError:
            raise df_exceptions.DBKeyNotFound(key=key)

    def set_key(self, table, key, value, topic=None):
        # This will raise exception if the key isn't found
        self.get_key(table, key, topic)
        table_dict = self._db[table]
        table_dict[key] = value

    def create_key(self, table, key, value, topic=None):
        table_dict = self._db[table]
        table_dict[key] = value

    def delete_key(self, table, key, topic=None):
        table_dict = self._db[table]
        del table_dict[key]

    def get_all_entries(self, table, topic=None):
        table_dict = self._db[table]
        return [value for value in table_dict.values()]

    def get_all_keys(self, table, topic=None):
        table_dict = self._db[table]
        return [key for key in table_dict.keys()]

    def allocate_unique_key(self, table):
        with self._unique_keys_lock:
            unique_key_table = self._db[db_common.UNIQUE_KEY_TABLE]
            unique_key = unique_key_table.get(table, 0) + 1
            unique_key_table[table] = unique_key
        return unique_key

    def process_ha(self):
        # Do nothing
        pass

    def set_neutron_server(self, is_neutron_server):
        # Do nothing
        pass
