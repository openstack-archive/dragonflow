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

from dragonflow._i18n import _LE
from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import db_api
from dragonflow.db.drivers.redis_mgt import RedisMgt
from oslo_log import log

import re
import redis
import six

LOG = log.getLogger(__name__)


class RedisDbDriver(db_api.DbApi):

    def __init__(self):
        super(RedisDbDriver, self).__init__()
        self.clients = {}
        self.remote_server_lists = []
        self.redis_mgt = None

    def initialize(self, db_ip, db_port, **args):
        # get remote ip port list
        self.redis_mgt = RedisMgt.get_instance(db_ip, db_port)
        self.remote_server_lists = self.redis_mgt.get_master_list()
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

    def get_key(self, table, key, topic=None):
        if topic is None:
            local_key = self.uuid_to_key(table, key, '*')
            try:
                for client in six.itervalues(self.clients):
                    local_keys = client.keys(local_key)
                    if len(local_keys) == 1:
                        return client.get(local_keys[0])
            except Exception as e:
                LOG.exception(_LE("exception %(key)s: %(e)s")
                              % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)
        else:
            local_key = self.uuid_to_key(table, key, topic)
            try:
                client = self._get_client(local_key)
                # return nil if not found
                return client.get(local_key)
            except Exception as e:
                LOG.exception(_LE("exception %(key)s: %(e)s")
                              % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)

    def set_key(self, table, key, value, topic=None):
        local_key = self.uuid_to_key(table, key, topic)
        try:
            client = self._get_client(local_key)
            res = client.set(local_key, value)
            if not res:
                client.delete(local_key)
            return res
        except Exception as e:
            LOG.exception(_LE("exception %(key)s: %(e)s")
                          % {'key': local_key, 'e': e})
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def create_key(self, table, key, value, topic=None):
        return self.set_key(table, key, value, topic)

    def delete_key(self, table, key, topic=None):
        local_topic = topic
        local_key = self.uuid_to_key(table, key, local_topic)
        try:
            client = self._get_client(local_key)
            return client.delete(local_key)
        except Exception as e:
            LOG.exception(_LE("exception %(key)s: %(e)s")
                          % {'key': local_key, 'e': e})
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def get_all_entries(self, table, topic=None):
        res = []
        if topic is None:
            local_key = self.uuid_to_key(table, '*', '*')
            try:
                for client in six.itervalues(self.clients):
                    local_keys = client.keys(local_key)
                    if len(local_keys) > 0:
                        for tmp_key in local_keys:
                            res.append(client.get(tmp_key))
                return res
            except Exception as e:
                LOG.exception(_LE("exception %(key)s: %(e)s")
                              % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)
        else:
            local_key = self.uuid_to_key(table, '*', topic)
            try:
                client = self._get_client(local_key)
                local_keys = client.keys(local_key)
                if len(local_keys) > 0:
                    res.extend(client.mget(local_keys))
                return res
            except Exception as e:
                LOG.exception(_LE("exception %(key)s: %(e)s")
                              % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)

    def get_all_keys(self, table, topic=None):
        if topic is None:
            res = []
            local_key = self.uuid_to_key(table, '*', '*')
            try:
                for client in six.itervalues(self.clients):
                    res.extend(client.keys(local_key))
                return [self._strip_table_name_from_key(key) for key in res]
            except Exception as e:
                LOG.exception(_LE("exception %(key)s: %(e)s")
                              % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)
        else:
            local_key = self.uuid_to_key(table, '*', topic)
            try:
                client = self._get_client(local_key)
                res = client.keys(local_key)
                return [self._strip_table_name_from_key(key) for key in res]
            except Exception as e:
                LOG.exception(_LE("exception %(key)s: %(e)s")
                              % {'key': local_key, 'e': e})
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def _strip_table_name_from_key(self, key):
        regex = '^{.*}\\.(.*)$'
        m = re.match(regex, key)
        return m.group(1)

    def _allocate_unique_key(self):
        local_key = self.uuid_to_key('tunnel_key', 'key', None)
        try:
            client = self._get_client(local_key)
            return client.incr(local_key)
        except Exception as e:
            raise e

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

    def _get_client(self, key):
        ip_port = self.redis_mgt.get_ip_by_key(key)
        client = self.clients.get(ip_port, None)
        if client is not None:
            return self.clients[ip_port]
        else:
            raise df_exceptions.DBClientNotFound(ip=ip_port)

    def register_topic_for_notification(self, topic):
        pass

    def unregister_topic_for_notification(self, topic):
        pass
