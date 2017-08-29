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
import rethinkdb as rdb

from dragonflow.common import exceptions
from dragonflow import conf as cfg
from dragonflow.db import db_api

_DF_DATABASE = 'dragonflow'


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
            conn_pool_size = cfg.CONF.df_rethinkdb.connection_pool_size
            if self._pool.empty() and self._pool_size < conn_pool_size:
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
            try:
                res = self._query_key(table, key).run(conn)
            except rdb.errors.ReqlOpFailedError:
                res = None
        if res is None:
            raise exceptions.DBKeyNotFound(key=key)
        return res['value']

    def set_key(self, table, key, value, topic=None):
        # FIXME cannot marshall None values
        with self._get_conn() as conn:
            res = self._query_key(table, key).update({
                'id': key,
                'value': value,
            }).run(conn)

        if res['skipped'] == 1:
            raise exceptions.DBKeyNotFound(key=key)

    def create_key(self, table, key, value, topic=None):
        with self._get_conn() as conn:
            rdb.table(table).insert({
                'id': key,
                'value': value,
            }).run(conn)

    def delete_key(self, table, key, topic=None):
        with self._get_conn() as conn:
            res = self._query_key(table, key).delete().run(conn)

        if res['skipped'] == 1:
            raise exceptions.DBKeyNotFound(key=key)

    def get_all_entries(self, table, topic=None):
        with self._get_conn() as conn:
            try:
                cursor = rdb.table(table).pluck('value').run(conn)
            except rdb.errors.ReqlOpFailedError:
                return []
            return [entry['value'] for entry in cursor]

    def get_all_keys(self, table, topic=None):
        with self._get_conn() as conn:
            try:
                cursor = rdb.table(table).pluck("id").run(conn)
            except rdb.errors.ReqlOpFailedError:
                return []
            return [entry['id'] for entry in cursor]

    def allocate_unique_key(self, table_name):
        self._ensure_table_exists('unique_key')
        with self._get_conn() as conn:
            res = rdb.table('unique_key').get(table_name).replace(
                lambda post: {'id': table_name,
                              'key': post['key'].default(0).add(1)},
                return_changes=True,
            ).run(conn)
            return res['changes'][0]['new_val']['key']

    def _ensure_table_exists(self, table):
        with self._get_conn() as conn:
            if table not in rdb.table_list().run(conn):
                rdb.table_create(table).run(conn)

    def process_ha(self):
        pass

    def set_neutron_server(self, is_neutron_server):
        pass  # Not implemented
