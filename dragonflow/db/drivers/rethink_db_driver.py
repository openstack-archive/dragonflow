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

from dragonflow.db import db_api
from oslo_serialization import jsonutils
import rethinkdb
import threading
import time


class RethinkDbDriver(db_api.DbApi):
    db_ip = None
    db_port = None
    runThreads = True

    def __init__(self):
        super(RethinkDbDriver, self).__init__()
        self.client = rethinkdb
        self.current_key = 0
        self.db_name = 'dragonflow'

    def __del__(self):
        self.runThreads = False

    def initialize(self, db_ip, db_port, **args):
        self.db_ip = db_ip
        self.db_port = db_port
        self.client.connect(host=db_ip, port=db_port).repl()

    def support_publish_subscribe(self):
        return True

    def get_key(self, table, key):
        return jsonutils.dumps(self.client.db('dragonflow').table(table).
                               get(key).run())

    def set_key(self, table, key, value):
        self.client.db('dragonflow').table(table).get(key).\
            update(jsonutils.loads(value), return_changes=True).run()

    def create_key(self, table, key, value):
        self.client.db('dragonflow').table(table).\
            insert(jsonutils.loads(value), return_changes=True).run()

    def delete_key(self, table, key):
        self.client.db('dragonflow').table(table).get(key).delete().run()

    def get_all_entries(self, table):
        res = []
        cursor = self.client.db('dragonflow').table(table).run()
        for entry in cursor:
            res.append(jsonutils.dumps(entry))
        return res

    def get_all_keys(self, table):
        res = []
        cursor = self.client.db('dragonflow').table(table).pluck("name").run()
        for entry in cursor:
            res.append(jsonutils.dumps(entry))
        return res

    def single_feed(self, table, callback):
        conn = self.client.connect(host=self.db_ip, port=self.db_port)
        cursor = self.client.db('dragonflow').table(table).changes().run(conn)
        for entry in cursor:
            if entry['old_val'] is None:
                act = {'action': 'create'}
                key = entry['new_val']['name']
            elif entry['new_val'] is None:
                act = {'action': 'delete'}
                key = entry['old_val']['name']
            else:
                act = {'action': 'set'}
                key = entry['new_val']['name']
            attempts = 0
            while self.runThreads:
                try:
                    callback(table, key, act, entry['new_val'])
                    break
                except Exception as e:
                    if attempts < 1000:
                        pass
                    else:
                        raise e
                attempts += 1
                time.sleep(1)

    def register_notification_callback(self, callback, prefix=None):
        all_tables = self.client.db('dragonflow').table_list().run()
        for table in all_tables:
            if table.encode('ascii', 'ignore').startswith(prefix):
                try:
                    t = threading.Thread(target=self.single_feed,
                                         args=(table, callback))
                    t.daemon = True
                    t.start()
                except Exception as e:
                    raise e

    @property
    def _allocate_unique_key(self):
        table = 'tunnel_key'
        db_id = 1
        prev_value = 0
        try:
            return_val = self.client.db('dragonflow').table(table).\
                get(db_id).update({'key': self.client.row['key'].
                                  add(1)}, return_changes=True).run()
            new_value = return_val['changes'][0]['new_val']['key']
            prev_value = return_val['changes'][0]['old_val']['key']
            return new_value
        except Exception as e:
            if prev_value == 0:
                self.client.db('dragonflow').table(table).\
                    insert({'name': db_id, 'key': 1},
                           return_changes=False).run()
                return 1
            raise e

    def allocate_unique_key(self):
        while True:
            try:
                return self._allocate_unique_key
            except Exception:
                pass
