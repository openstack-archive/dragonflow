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
import threading

from eventlet import queue
from oslo_serialization import jsonutils
import rethinkdb as rdb

from dragonflow.common.exceptions import DBKeyNotFound
from dragonflow.db import db_api

_DF_DATABASE = 'dragonflow'
_CONN_POOL_SIZE = 10  # FIXME: move to configuration maybe?


class RethinkDbDriver(db_api.DbApi):
    def __init__(self):
        super(RethinkDbDriver, self).__init__()
        self._pool = queue.Queue()
        self._pool_size = 0
        self._pool_lock = threading.Lock()

    def _create_connection(self):
        return rdb.connect(host=self._db_host, port=self._db_port,
                           db=_DF_DATABASE)

    @contextlib.contextmanager
    def _get_conn(self):
        with self._pool_lock:
            if self._pool.empty() and self._pool_size < _CONN_POOL_SIZE:
                conn = self._create_connection()
                self._pool_size += 1
            else:
                conn = None
        try:
            if conn is None:
                conn = self._pool.get()
            yield conn
        finally:
            self._pool.put(conn)

    def initialize(self, db_ip, db_port, **args):
        self._db_host = db_ip
        self._db_port = db_port

    def support_publish_subscribe(self):
        return False

    def create_table(self, table):
        with self._get_conn() as conn:
            rdb.table_create(table).run(conn)

    def delete_table(self, table):
        with self._get_conn() as conn:
            rdb.table_drop(table).run(conn)

    def _query_key(self, table, key):
        return rdb.table(table).get(key)

    def get_key(self, table, key, topic=None):
        with self._get_conn() as conn:
            res = self._query_key(table, key).run(conn)
        if res is None:
            raise DBKeyNotFound(key=key)
        return jsonutils.dumps(res)

    def set_key(self, table, key, value, topic=None):
        # FIXME cannot marshall None values
        obj = jsonutils.loads(value)
        with self._get_conn() as conn:
            res = self._query_key(table, key).update(obj).run(conn)

        if res['skipped'] == 1:
            raise DBKeyNotFound(key=key)

    def create_key(self, table, key, value, topic=None):
        obj = jsonutils.loads(value)
        with self._get_conn() as conn:
            rdb.table(table).insert(obj).run(conn)

    def delete_key(self, table, key, topic=None):
        with self._get_conn() as conn:
            res = self._query_key(table, key).delete().run(conn)

        if res['skipped'] == 1:
            raise DBKeyNotFound(key=key)

    def get_all_entries(self, table, topic=None):
        with self._get_conn() as conn:
            cursor = rdb.table(table).run(conn)
            return [jsonutils.dumps(entry) for entry in cursor]

    def get_all_keys(self, table, topic=None):
        with self._get_conn() as conn:
            cursor = rdb.table(table).pluck("id").run(conn)
            return [entry['id'] for entry in cursor]

    def register_notification_callback(self, callback, topics=None):
        pass

    def register_topic_for_notification(self, topic):
        pass

    def unregister_topic_for_notification(self, topic):
        pass

    def allocate_unique_key(self):
        self._ensure_table_exists('unique_key')
        db_id = 1

        with self._get_conn() as conn:
            res = rdb.table('unique_key').get(db_id).update(
                {'key': rdb.row['key'].add(1)},
                return_changes=True,
            ).run(conn)

            if res['skipped'] == 1:
                # No initial key
                rdb.table('unique_key').insert({'id': db_id, 'key': 1})\
                    .run(conn)
                return 1

            else:
                return res['changes'][0]['new_val']['key']

    def _ensure_table_exists(self, table):
        with self._get_conn() as conn:
            if table not in rdb.table_list().run(conn):
                rdb.table_create(table).run(conn)

    def process_ha(self):
        pass
