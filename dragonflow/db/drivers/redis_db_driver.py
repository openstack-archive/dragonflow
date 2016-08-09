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

import re

from oslo_log import log
import redis
from redis.exceptions import (
    ConnectionError,
    ResponseError,
)
import six

from dragonflow._i18n import _LI, _LE, _LW
from dragonflow.db import db_api
from dragonflow.db.drivers.redis_mgt import RedisMgt


LOG = log.getLogger(__name__)


class RedisDbDriver(db_api.DbApi):

    RequestRetryTimes = 5

    def __init__(self):
        super(RedisDbDriver, self).__init__()
        self.clients = {}
        self.remote_server_lists = []
        self.redis_mgt = None

    def initialize(self, db_ip, db_port, **args):
        # get remote ip port list
        self.redis_mgt = RedisMgt.get_instance(db_ip, db_port)
        self._update_server_list()

    def _update_server_list(self):
        if self.redis_mgt is not None:
            self.remote_server_lists = self.redis_mgt.get_master_list()
            self.clients = {}
            for remote in self.remote_server_lists:
                remote_ip_port = remote['ip_port']
                ip_port = remote_ip_port.split(':')
                self.clients[remote_ip_port] = \
                    redis.client.StrictRedis(host=ip_port[0], port=ip_port[1])

    def support_publish_subscribe(self):
        return True

    def create_table(self, table):
        # Not needed in redis
        pass

    def delete_table(self, table):
        # Not needed in redis
        pass

    def _handle_db_conn_error(self, ip_port, local_key=None):
        self.redis_mgt.remove_node_from_master_list(ip_port)
        self._update_server_list()

        if local_key is not None:
            LOG.exception(_LE("update server list, key: %(key)s")
                          % {'key': local_key})

    def _sync_master_list(self):
        result = self.redis_mgt.redis_get_master_list_from_syncstring(
            RedisMgt.global_sharedlist.raw)
        if result:
            self._update_server_list()

    def _gen_args(self, local_key, value):
        args = []
        args.append(local_key)
        if value is not None:
            args.append(value)

        return args

    def _is_oper_valid(self, oper):
        if oper == 'SET' or oper == 'GET' or oper == 'DEL':
            return True

        return False

    def _execute_cmd(self, oper, local_key, value=None):
        if not self._is_oper_valid(oper):
            LOG.warning(_LW("invalid oper: %(oper)s")
                        % {'oper': oper})
            return None
        self._sync_master_list()
        ip_port = self.redis_mgt.get_ip_by_key(local_key)
        client = self._get_client(local_key)
        if client is None:
            return None

        arg = self._gen_args(local_key, value)

        ttl = self.RequestRetryTimes
        asking = False
        alreadysync = False
        while ttl > 0:
            ttl -= 1
            try:
                if asking:
                    client.execute_command('ASKING')
                    asking = False

                return client.execute_command(oper, *arg)
            except ConnectionError as e:
                if not alreadysync:
                    LOG.info(_LI("redis driver sync old masterlist %s")
                             % self.redis_mgt.master_list)
                    self._sync_master_list()
                    LOG.info(_LI("redis driver sync new masterlist %s")
                             % self.redis_mgt.master_list)
                    alreadysync = True
                    continue
                self._handle_db_conn_error(ip_port, local_key)
                LOG.exception(_LE("connection error while sending "
                                  "request to db: %(e)s") % {'e': e})
                raise e
            except ResponseError as e:
                if not alreadysync:
                    LOG.info(_LI("redis driver sync old masterlist %s")
                             % self.redis_mgt.master_list)
                    self._sync_master_list()
                    LOG.info(_LI("redis driver sync new masterlist %s")
                             % self.redis_mgt.master_list)
                    alreadysync = True
                    continue
                resp = str(e).split(' ')
                if 'ASK' in resp[0]:
                    # one-time flag to force a node to serve a query about an
                    # IMPORTING slot
                    asking = True

                if 'ASK' in resp[0] or 'MOVE' in resp[0]:
                    # MOVED/ASK XXX X.X.X.X:X
                    # do redirection
                    client = self._get_client(host=resp[2])
                    if client is None:
                        # maybe there is a fast failover
                        self._handle_db_conn_error(ip_port, local_key)
                        LOG.exception(_LE("no client available: "
                                          "%(ip_port)s, %(e)s")
                                      % {'ip_port': resp[2], 'e': e})
                        raise e
                else:
                    LOG.exception(_LE("error not handled: %(e)s")
                                  % {'e': e})
                    raise e
            except Exception as e:
                if not alreadysync:
                    LOG.info(_LI("redis driver sync old masterlist %s")
                             % self.redis_mgt.master_list)
                    self._sync_master_list()
                    LOG.info(_LI("redis driver sync new masterlist %s")
                             % self.redis_mgt.master_list)
                    alreadysync = True
                    continue
                self._handle_db_conn_error(ip_port, local_key)
                LOG.exception(_LE("exception while sending request to "
                                  "db: %(e)s") % {'e': e})
                raise e

    def get_key(self, table, key, topic=None):
        if topic is None:
            local_key = self.uuid_to_key(table, key, '*')
            try:
                for host, client in six.iteritems(self.clients):
                    local_keys = client.keys(local_key)
                    if len(local_keys) == 1:
                        return self._execute_cmd("GET", local_keys[0])
            except Exception:
                LOG.exception(_LE("exception when get_key: %(key)s ")
                              % {'key': local_key})

        else:
            local_key = self.uuid_to_key(table, key, topic)
            try:
                # return nil if not found
                return self._execute_cmd("GET", local_key)
            except Exception:
                LOG.exception(_LE("exception when get_key: %(key)s ")
                              % {'key': local_key})

    def set_key(self, table, key, value, topic=None):
        local_key = self.uuid_to_key(table, key, topic)

        try:
            res = self._execute_cmd("SET", local_key, value)
            if res is None:
                res = 0

            return res
        except Exception:
            LOG.exception(_LE("exception when set_key: %(key)s ")
                          % {'key': local_key})

    def create_key(self, table, key, value, topic=None):
        return self.set_key(table, key, value, topic)

    def delete_key(self, table, key, topic=None):
        local_topic = topic
        local_key = self.uuid_to_key(table, key, local_topic)

        try:
            res = self._execute_cmd("DEL", local_key)
            if res is None:
                res = 0

            return res
        except Exception:
            LOG.exception(_LE("exception when delete_key: %(key)s ")
                          % {'key': local_key})

    def get_all_entries(self, table, topic=None):
        res = []
        ip_port = None
        if topic is None:
            local_key = self.uuid_to_key(table, '*', '*')
            try:
                for host, client in six.iteritems(self.clients):
                    local_keys = client.keys(local_key)
                    if len(local_keys) > 0:
                        for tmp_key in local_keys:
                            res.append(self._execute_cmd("GET", tmp_key))
                return res
            except Exception:
                LOG.exception(_LE("exception when get_all_entries: "
                                  "%(key)s ")
                              % {'key': local_key})

        else:
            local_key = self.uuid_to_key(table, '*', topic)
            try:
                self._sync_master_list()
                ip_port = self.redis_mgt.get_ip_by_key(local_key)
                client = self._get_client(local_key)
                if client is None:
                    return res

                local_keys = client.keys(local_key)
                if len(local_keys) > 0:
                    res.extend(client.mget(local_keys))
                return res
            except Exception as e:
                self._handle_db_conn_error(ip_port, local_key)
                LOG.exception(_LE("exception when mget: %(key)s, %(e)s")
                              % {'key': local_key, 'e': e})

    def get_all_keys(self, table, topic=None):
        res = []
        ip_port = None
        if topic is None:
            local_key = self.uuid_to_key(table, '*', '*')
            try:
                for host, client in six.iteritems(self.clients):
                    ip_port = host
                    res.extend(client.keys(local_key))
                return [self._strip_table_name_from_key(key) for key in res]
            except Exception as e:
                self._handle_db_conn_error(ip_port, local_key)
                LOG.exception(_LE("exception when get_all_keys: "
                                  "%(key)s, %(e)s")
                              % {'key': local_key, 'e': e})

        else:
            local_key = self.uuid_to_key(table, '*', topic)
            try:
                self._sync_master_list()
                ip_port = self.redis_mgt.get_ip_by_key(local_key)
                client = self._get_client(local_key)
                if client is None:
                    return res

                res = client.keys(local_key)
                return [self._strip_table_name_from_key(key) for key in res]

            except Exception as e:
                self._handle_db_conn_error(ip_port, local_key)
                LOG.exception(_LE("exception when get_all_keys: "
                                  "%(key)s, %(e)s")
                              % {'key': local_key, 'e': e})

    def _strip_table_name_from_key(self, key):
        regex = '^{.*}\\.(.*)$'
        m = re.match(regex, key)
        return m.group(1)

    def _allocate_unique_key(self):
        local_key = self.uuid_to_key('tunnel_key', 'key', None)
        ip_port = None
        try:
            self._sync_master_list()
            ip_port = self.redis_mgt.get_ip_by_key(local_key)
            client = self._get_client(local_key)
            if client is None:
                return None
            return client.incr(local_key)
        except Exception as e:
            self._handle_db_conn_error(ip_port, local_key)
            LOG.exception(_LE("exception when incr: %(key)s, %(e)s")
                          % {'key': local_key, 'e': e})

    def allocate_unique_key(self):
        try:
            return self._allocate_unique_key()
        except Exception as e:
            LOG.error(_LE("allocate_unique_key exception: %(e)s")
                      % {'e': e})
            return

    def register_notification_callback(self, callback, topics=None):
        pass

    def uuid_to_key(self, table, key, topic):
        if topic is None:
            local_key = ('{' + table + '.' + '}' + '.' + key)
        else:
            local_key = ('{' + table + '.' + topic + '}' + '.' + key)
        return local_key

    def check_connection(self, ip_port):
        try:
            if self.clients[ip_port] is None:
                return False
            self.clients[ip_port].get(None)
        except (redis.exceptions.ConnectionError,
                redis.exceptions.BusyLoadingError):
            return False
        return True

    def _get_client(self, key=None, host=None):
        if host is None:
            ip_port = self.redis_mgt.get_ip_by_key(key)
            if ip_port is None:
                return None
        else:
            ip_port = host

        client = self.clients.get(ip_port, None)
        if client is not None:
            return self.clients[ip_port]
        else:
            return None

    def process_ha(self):
        result = self.redis_mgt.redis_get_master_list_from_syncstring(
            RedisMgt.global_sharedlist.raw)
        if result:
            self._update_server_list()

    def register_topic_for_notification(self, topic):
        pass

    def unregister_topic_for_notification(self, topic):
        pass
