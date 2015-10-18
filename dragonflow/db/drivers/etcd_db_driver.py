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

import etcd

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import db_api


class EtcdDbDriver(db_api.DbApi):

    def __init__(self):
        super(EtcdDbDriver, self).__init__()
        self.client = None
        self.current_key = 0

    def initialize(self, db_ip, db_port, **args):
        self.client = etcd.Client(host=db_ip, port=db_port)

    def support_publish_subscribe(self):
        return False

    def get_key(self, table, key):
        try:
            return self.client.read('/' + table + '/' + key).value
        except etcd.EtcdKeyNotFound:
            raise df_exceptions.DBKeyNotFound(key=key)

    def set_key(self, table, key, value):
        # Verify that key exists
        self.get_key(table, key)

        self.client.write('/' + table + '/' + key, value)

    def create_key(self, table, key, value):
        self.client.write('/' + table + '/' + key, value)

    def delete_key(self, table, key):
        try:
            self.client.delete('/' + table + '/' + key)
        except etcd.EtcdKeyNotFound:
            raise df_exceptions.DBKeyNotFound(key=key)

    def get_all_entries(self, table):
        res = []
        directory = self.client.get("/" + table)
        for entry in directory.children:
            res.append(entry.value)
        return res

    def _allocate_unique_key(self):
        key = '/tunnel_key/key'
        prev_value = 0
        try:
            prev_value = int(self.client.read(key).value)
            self.client.test_and_set(key, str(prev_value + 1), str(prev_value))
            return prev_value + 1
        except Exception as e:
            if prev_value == 0:
                self.client.write(key, "1", prevExist=False)
                return 1
            raise e

    def allocate_unique_key(self):
        while True:
            try:
                return self._allocate_unique_key()
            except Exception:
                pass

    def wait_for_db_changes(self, callback):
        entry = self.client.read('/', wait=True, recursive=True,
                                 waitIndex=self.current_key)
        keys = entry.key.split('/')
        callback(keys[1], keys[2], entry.action, entry.value)
        self.current_key = entry.modifiedIndex + 1
