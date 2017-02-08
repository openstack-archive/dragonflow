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

import kazoo
from kazoo import client
from kazoo.handlers import eventlet
from kazoo import retry
import six

from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils
from dragonflow.db import db_api

ROOT_NS = '/openstack'

CLIENT_CONNECTION_RETRIES = -1

ZK_MAX_RETRIES = 3


def _parse_hosts(hosts):
    if isinstance(hosts, six.string_types):
        return hosts.strip()
    if isinstance(hosts, (dict)):
        host_ports = []
        for (k, v) in hosts.items():
            host_ports.append("%s:%s" % (k, v))
        hosts = host_ports
    if isinstance(hosts, (list, set, tuple)):
        return ",".join([str(h) for h in hosts])
    return hosts


class ZookeeperDbDriver(db_api.DbApi):

    def __init__(self):
        super(ZookeeperDbDriver, self).__init__()
        self.client = None
        self.db_ip = None
        self.db_port = None
        self.config = None

    def initialize(self, db_ip, db_port, **args):
        self.db_ip = db_ip
        self.db_port = db_port
        self.config = args['config']

    def _lazy_initialize(self):
        if not self.client:
            hosts = _parse_hosts(self.config.remote_db_hosts)
            _handler = eventlet.SequentialEventletHandler()
            _retry = retry.KazooRetry(max_tries=CLIENT_CONNECTION_RETRIES,
                                delay=0.5,
                                backoff=2,
                                sleep_func=_handler.sleep_func)
            self.client = client.KazooClient(hosts=hosts,
                                      handler=_handler,
                                      connection_retry=_retry)
            self.client.start()
            self.client.ensure_path(ROOT_NS)

    def support_publish_subscribe(self):
        return False

    def _generate_path(self, table, key):
        if not key:
            return ROOT_NS + '/' + table
        else:
            return ROOT_NS + '/' + table + '/' + key

    def get_key(self, table, key, topic=None):
        path = self._generate_path(table, key)
        try:
            self._lazy_initialize()
            ret = self.client.get(path)[0]
            return ret
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    @utils.wrap_func_retry(max_retries=ZK_MAX_RETRIES,
                           retry_interval=1,
                           inc_retry_interval=True,
                           max_retry_interval=10,
                           _errors=[kazoo.exceptions.SessionExpiredError])
    def create_table(self, table):
        path = self._generate_path(table, None)
        self._lazy_initialize()
        self.client.ensure_path(path)

    @utils.wrap_func_retry(max_retries=ZK_MAX_RETRIES,
                           retry_interval=1,
                           inc_retry_interval=True,
                           max_retry_interval=10,
                           _errors=[kazoo.exceptions.SessionExpiredError])
    def delete_table(self, table):
        path = self._generate_path(table, None)
        try:
            self._lazy_initialize()
            self.client.delete(path, recursive=True)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=table)

    @utils.wrap_func_retry(max_retries=ZK_MAX_RETRIES,
                           retry_interval=1,
                           inc_retry_interval=True,
                           max_retry_interval=10,
                           _errors=[kazoo.exceptions.SessionExpiredError])
    def set_key(self, table, key, value, topic=None):
        path = self._generate_path(table, key)
        try:
            self._lazy_initialize()
            self.client.set(path, value)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    @utils.wrap_func_retry(max_retries=ZK_MAX_RETRIES,
                           retry_interval=1,
                           inc_retry_interval=True,
                           max_retry_interval=10,
                           _errors=[kazoo.exceptions.SessionExpiredError])
    def create_key(self, table, key, value, topic=None):
        path = self._generate_path(table, key)
        self._lazy_initialize()
        self.client.create(path, value, makepath=True)

    @utils.wrap_func_retry(max_retries=ZK_MAX_RETRIES,
                           retry_interval=1,
                           inc_retry_interval=True,
                           max_retry_interval=10,
                           _errors=[kazoo.exceptions.SessionExpiredError])
    def delete_key(self, table, key, topic=None):
        path = self._generate_path(table, key)
        try:
            self._lazy_initialize()
            self.client.delete(path)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    def get_all_entries(self, table, topic=None):
        res = []
        path = self._generate_path(table, None)
        try:
            self._lazy_initialize()
            directory = self.client.get_children(path)
            for key in directory:
                res.append(self.get_key(table, key))
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=table)
        return res

    def get_all_keys(self, table, topic=None):
        path = self._generate_path(table, None)
        try:
            self._lazy_initialize()
            return self.client.get_children(path)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=table)

    def _allocate_unique_key(self, table):
        path = self._generate_path('unique_key', table)

        prev_value = 0
        while True:
            try:
                prev_value, stat = self.client.get(path)
                prev_value = int(prev_value)
                prev_version = stat.version
                self.client.set(path, str(prev_value + 1), prev_version)
                return prev_value + 1
            except kazoo.exceptions.BadVersionError:
                pass
            except kazoo.exceptions.NoNodeError:
                self.client.create(path, "1", makepath=True)
                return 1

    def allocate_unique_key(self, table):
        self._lazy_initialize()
        return self._allocate_unique_key(table)

    def register_notification_callback(self, callback):
        #NOTE(nick-ma-z): The pub-sub mechanism is not initially supported.
        #                 The watcher function of Zookeeper only supports
        #                 one-time trigger. You have to continuously register
        #                 watchers for each children. Moreover, the delay
        #                 between trigger and registration causes lose of
        #                 events. The DataWatch of Kazoo is also not that
        #                 stable and easy to use. Thanks to build-in pub-sub
        #                 of dragonflow, we don't need to work hard on zk side.
        return

    def register_topic_for_notification(self, topic):
        # Not needed until register notification callback is implemented
        pass

    def unregister_topic_for_notification(self, topic):
        # Not needed until register notification callback is implemented
        pass

    def process_ha(self):
        # Not needed in zookeeper
        pass

    def set_neutron_server(self, is_neutron_server):
        # Not needed in zookeeper
        pass
