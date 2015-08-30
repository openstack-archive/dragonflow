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

from dragonflow.db import db_api


class EtcdDbDriver(db_api.DbApi):

    def __init__(self):
        super(EtcdDbDriver, self).__init__()
        self.client = None
        self.current_key = 0

    def initialize(self, db_ip, db_port, **args):
        self.client = etcd.Client(host=db_ip, port=db_port)

    def support_publish_subscribe(self):
        return True

    def get_key(self, table, key):
        return self.client.read('/' + table + '/' + key).value

    def set_key(self, table, key, value):
        self.client.write('/' + table + '/' + key, value)

    def create_key(self, table, key, value):
        self.set_key(table, key, value)

    def delete_key(self, table, key):
        self.client.delete('/' + table + '/' + key)

    def get_all_entries(self, table):
        res = []
        directory = self.client.get("/" + table)
        for entry in directory.children:
            res.append(entry.value)
        return res

    def wait_for_db_changes(self, callback):
        entry = self.client.read('/', wait=True, recursive=True,
                                 waitIndex=self.current_key)
        keys = entry.key.split('/')
        callback(keys[1], keys[2], entry.action, entry.value)
        self.current_key = entry.modifiedIndex + 1
