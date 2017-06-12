# Copyright (c) 2015 OpenStack Foundation.
# All Rights Reserved.
#
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


class TenantDbStore(object):

    def __init__(self):
        self.activeports = {}
        self.lock = threading.Lock()
        self._table_name_mapping = {
        }

    def _get_table_by_name(self, table_name):
        return self._table_name_mapping[table_name]

    def get(self, table_name, key):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.get(key)

    def set(self, table_name, key, value):
        table = self._get_table_by_name(table_name)
        with self.lock:
            table[key] = value

    def pop(self, table_name, key):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.pop(key, None)

    def keys(self, table_name):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.keys()

    def values(self, table_name):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.values()

    def clear(self):
        with self.lock:
            for table_name in self._table_name_mapping:
                self._table_name_mapping[table_name].clear()


class DbStore(object):

    def __init__(self):
        self.tenant_dbs = collections.defaultdict(TenantDbStore)

    def get(self, table_name, key, topic):
        if topic:
            return self.tenant_dbs[topic].get(table_name, key)
        for tenant_db in self.tenant_dbs.values():
            value = tenant_db.get(table_name, key)
            if value:
                return value

    def keys(self, table_name, topic):
        if topic:
            return self.tenant_dbs[topic].keys(table_name)
        result = []
        for tenant_db in self.tenant_dbs.values():
            result.extend(tenant_db.keys(table_name))
        return result

    def values(self, table_name, topic):
        if topic:
            return self.tenant_dbs[topic].values(table_name)
        result = []
        for tenant_db in self.tenant_dbs.values():
            result.extend(tenant_db.values(table_name))
        return result

    def set(self, table_name, key, value, topic):
        if not topic:
            topic = value.get_topic()
        self.tenant_dbs[topic].set(table_name, key, value)

    def delete(self, table_name, key, topic):
        if topic:
            self.tenant_dbs[topic].pop(table_name, key)
        else:
            for tenant_db in self.tenant_dbs.values():
                if tenant_db.pop(table_name, key):
                    break

    def get_unique_key_by_id(self, table_name, key, topic=None):
        table_item = self.get(table_name, key, topic)
        if table_item:
            return table_item.get_unique_key()

    def clear(self, topic=None):
        if not topic:
            for tenant_db in self.tenant_dbs.values():
                tenant_db.clear()
        else:
            self.tenant_dbs[topic].clear()
