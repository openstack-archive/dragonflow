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
from kazoo.client import KazooClient
from kazoo.handlers.eventlet import SequentialEventletHandler
from kazoo.retry import KazooRetry

from oslo_log import log
import six

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import db_api

LOG = log.getLogger(__name__)

ROOT_NS = '/openstack'

CONNECTION_RETRIES = 3


def _parse_hosts(hosts):
    if isinstance(hosts, six.string_types):
        return hosts.strip()
    if isinstance(hosts, (dict)):
        host_ports = []
        for (k, v) in six.iteritems(hosts):
            host_ports.append("%s:%s" % (k, v))
        hosts = host_ports
    if isinstance(hosts, (list, set, tuple)):
        return ",".join([str(h) for h in hosts])
    return hosts


class ZookeeperDbDriver(db_api.DbApi):

    def __init__(self):
        super(ZookeeperDbDriver, self).__init__()
        self.client = None

    def initialize(self, db_ip, db_port, **args):
        hosts = _parse_hosts(args['config'].remote_db_hosts)
        _handler = SequentialEventletHandler()
        _retry = KazooRetry(max_tries=CONNECTION_RETRIES, delay=0.5,
                            backoff=2, sleep_func=_handler.sleep_func)
        self.client = KazooClient(hosts=hosts,
                                  handler=_handler,
                                  connection_retry=_retry)
        self.client.start()
        self.client.ensure_path(ROOT_NS)

    def support_publish_subscribe(self):
        return True

    def _generate_path(self, table, key):
        if not key:
            return ROOT_NS + '/' + table
        else:
            return ROOT_NS + '/' + table + '/' + key

    def get_key(self, table, key):
        path = self._generate_path(table, key)
        try:
            ret = self.client.get(path)[0]
            return ret
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    def set_key(self, table, key, value):
        path = self._generate_path(table, key)
        try:
            ret = self.client.set(path, value)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)
        except kazoo.exceptions.ZookeeperError:
            raise df_exceptions.DBValueOutOfBounds(key=key, value=value)

    def create_key(self, table, key, value):
        path = self._generate_path(table, key)
        try:
            ret = self.client.create(path, value)
        except kazoo.exceptions.ZookeeperError:
            raise df_exceptions.DBValueOutOfBounds(key=key, value=value)

    def delete_key(self, table, key):
        path = self._generate_path(table, key)
        try:
            ret = self.client.delete(path)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=key)

    def get_all_entries(self, table):
        res = []
        path = self._generate_path(table, None)
        try:
            directory = self.client.get_children(path)
            for key in directory:
                res.append(self.get_key(table, key))
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=table)
        return res

    def get_all_keys(self, table):
        path = self._generate_path(table, None)
        try:
            return self.client.get_children(path)
        except kazoo.exceptions.NoNodeError:
            raise df_exceptions.DBKeyNotFound(key=table)

    def _allocate_unique_key(self):
        path = self._generate_path('/tunnel_key/key', None)
        prev_value = 0
        version_exception = True
        while version_exception:
            try:
                prev_value, stat = self.client.get(path)
                prev_value = int(prev_value)
                prev_version = stat.version
                self.client.set(path, str(prev_value + 1), prev_version)
                return prev_value + 1
            except kazoo.exceptions.BadVersionError:
                version_exception = True
            except kazoo.exceptions.NoNodeError:
                self.client.create(path, "1", makepath=True)
                return 1

    def allocate_unique_key(self):
        return self._allocate_unique_key()

    def register_notification_callback(self, callback):
        #NOTE(nick-ma-z): The pub-sub mechanism is not initially supported.
        #                 The watcher function of Zookeeper only supports
        #                 one-time trigger. You have to continuously register
        #                 watchers for each children. Moreover, the delay
        #                 between trigger and registration causes lose of
        #                 events. The DataWatch of Kazoo is also not that
        #                 stable and easy to use. Thanks to build-in pub-sub
        #                 of dragonflow, we don't need to work hard on zk side.
        #                 Please set 'use_df_pub_sub=True' in the configuration
        #                 to enable the build-in pub-sub function.
        return
