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

import ramcloud

from dragonflow.db import db_api


class RamCloudDbDriver(db_api.DbApi):

    def __init__(self):
        super(RamCloudDbDriver, self).__init__()
        self.client = None
        self.current_key = 0
        self.service_locator = None
        self.db_name = 'dragonflow'

    def create_tables(self, tables):
        for t in tables:
            self.client.drop_table(t)
            self.client.create_table(t)

    def initialize(self, db_ip, db_port, **args):
        self.client = ramcloud.RAMCloud()
        self.service_locator = 'fast+udp:host=' + db_ip \
                               + ',port=' + str(db_port) + ''
        self.client.connect(self.service_locator, self.db_name)

    def support_publish_subscribe(self):
        return False

    def get_key(self, table, key):
        table_id = self.client.get_table_id(table)
        value, version = self.client.read(table_id, key)
        return value

    def set_key(self, table, key, value):
        table_id = self.client.get_table_id(table)
        self.client.write(table_id, key, value)

    def create_key(self, table, key, value):
        self.set_key(table, key, value)

    def delete_key(self, table, key):
        table_id = self.client.get_table_id(table)
        self.client.delete(table_id, key)

    def get_all_entries(self, table, topic=None):
        res = []
        table_id = self.client.get_table_id(table)
        enumeration_state = self.client.enumerate_table_prepare(table_id)
        while True:
            key, value = self.client.enumerate_table_next(enumeration_state)
            if key == '':
                break
            res.append(value)
        self.client.enumerate_table_finalize(enumeration_state)
        return res

    def get_all_keys(self, table, topic=None):
        res = []
        table_id = self.client.get_table_id(table)
        enumeration_state = self.client.enumerate_table_prepare(table_id)
        while True:
            key, value = self.client.enumerate_table_next(enumeration_state)
            if key == '':
                break
            res.append(key)
        self.client.enumerate_table_finalize(enumeration_state)
        return res

    def _allocate_unique_key(self):
        table_id = self.client.get_table_id('tunnel_key')
        key = 1
        version_exception = True
        while version_exception:
            try:
                value, version = self.client.read(table_id, key)
                prev_value = int(value)
                self.client.write(table_id, key, str(prev_value + 1), version)
                return prev_value + 1
            except ramcloud.VersionError:
                version_exception = True
            except ramcloud.ObjectExistsError:
                self.client.write(table_id, key, str(0))

    def allocate_unique_key(self):
        return self._allocate_unique_key()

    def register_notification_callback(self, callback):
        pass

    def register_topic_for_notification(self, topic):
        # Not needed until register notification callback is implemented
        pass

    def unregister_topic_for_notification(self, topic):
        # Not needed until register notification callback is implemented
        pass
