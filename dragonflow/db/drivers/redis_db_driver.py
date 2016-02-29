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
import redis

LOG = log.getLogger(__name__)


class RedisDbDriver(db_api.DbApi):
    redis_mgt = RedisMgt()

    def __init__(self):
        super(RedisDbDriver, self).__init__()
        self.clients = {}
        self.remote_server_lists = []

    def initialize(self, db_ip, db_port, **args):
        # get remote ip port list
        RedisDbDriver.redis_mgt.init_default_node(db_ip, db_port)
        RedisDbDriver.redis_mgt.get_cluster_topology()
        self.remote_server_lists = RedisDbDriver.redis_mgt.get_master_list()
        for remote in self.remote_server_lists:
            ip_port = remote['ip_port'].split(':')
            self.clients[remote['ip_port']] = \
                redis.client.StrictRedis(host=ip_port[0], port=ip_port[1])

    def support_publish_subscribe(self):
        return True

    def get_key(self, table, key, topic=None):
        if topic is None:
            local_key = self.uuid_to_key(table, key, '*')
            try:
                for key in self.clients:
                    local_keys = self.clients[key].keys(local_key)
                    for tmp_key in local_keys:
                        return self.clients[key].get(tmp_key)
                return None
            except Exception as e:
                LOG.error(_LE("exception %(key)s: %(e)s")
                          % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)
        else:
            local_key = self.uuid_to_key(table, key, topic)
            try:
                client = self._get_client(local_key)
                # return nil if not found
                return client.get(local_key)
            except Exception as e:
                LOG.error(_LE("exception %(key)s: %(e)s")
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
            LOG.error(_LE("exception %(key)s: %(e)s")
                      % {'key': local_key, 'e': e})
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def create_key(self, table, key, value, topic=None):
        local_key = self.uuid_to_key(table, key, topic)
        try:
            client = self._get_client(local_key)
            res = client.set(local_key, value)
            if not res:
                client.delete(local_key)
            return res
        except Exception as e:
            LOG.error(_LE("exception %(key)s: %(e)s")
                      % {'key': local_key, 'e': e})
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def delete_key(self, table, key, topic=None):
        local_topic = topic
        local_key = self.uuid_to_key(table, key, local_topic)
        try:
            client = self._get_client(local_key)
            # return 0 if not found
            return client.delete(local_key)
        except Exception as e:
            LOG.error(_LE("exception %(key)s: %(e)s")
                      % {'key': local_key, 'e': e})
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def get_all_entries(self, table, topic=None):
        res = []
        if topic is None:
            local_topic = '*'
            local_key = self.uuid_to_key(table, '*', local_topic)
            try:
                for key in self.clients:
                    local_keys = self.clients[key].keys(local_key)
                    for tmp_key in local_keys:
                        res.append(self.clients[key].get(tmp_key))
                return res
            except Exception as e:
                LOG.error(_LE("exception %(key)s: %(e)s")
                          % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)
        else:
            local_key = self.uuid_to_key(table, '*', topic)
            try:
                client = self._get_client(local_key)
                local_keys = client.keys(local_key)
                for tmp_key in local_keys:
                    res.append(client.get(tmp_key))
                return res
            except Exception as e:
                LOG.error(_LE("exception %(key)s: %(e)s")
                          % {'key': local_key, 'e': e})
                raise df_exceptions.DBKeyNotFound(key=local_key)

    def get_all_keys(self, table, topic=None):
        local_topic = topic
        local_key = self.uuid_to_key(table, '*', local_topic)
        try:
            client = self._get_client(local_key)
            return client.keys(local_key)
        except Exception as e:
            LOG.error(_LE("exception %(key)s: %(e)s")
                      % {'key': local_key, 'e': e})
        raise df_exceptions.DBKeyNotFound(key=local_key)

    def _allocate_unique_key(self):
        local_key = self.uuid_to_key('tunnel_key', 'key', None)
        prev_value = 0
        client = None
        try:
            client = self._get_client(local_key)
            prev_value = int(client.get(local_key))
            client.set(local_key, str(prev_value + 1))
            return prev_value + 1
        except Exception as e:
            if (prev_value == 0) and (client is not None):
                client.set(local_key, "1")
                return 1
            raise e

    def allocate_unique_key(self):
        while True:
            try:
                return self._allocate_unique_key()
            except Exception as e:
                LOG.error("allocate_unique_key exception:%s", e.__str__())
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
                raise redis.exceptions.ConnectionError
            self.clients[ip_port].get(None)
        except (redis.exceptions.ConnectionError,
                redis.exceptions.BusyLoadingError):
            return False
        return True

    def _get_client(self, key):
        ip_port = RedisDbDriver.redis_mgt.get_ip_by_key(key)
        if ip_port in self.clients:
            return self.clients[ip_port]
        else:
            raise Exception('get client failed ip_port = %(ip_port)s')

    def register_topic_for_notification(self, topic):
        pass

    def unregister_topic_for_notification(self, topic):
        pass
