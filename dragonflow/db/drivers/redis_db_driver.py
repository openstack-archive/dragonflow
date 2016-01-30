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

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db.drivers.redis_mgt import RedisMgt
from dragonflow.db import db_api
from oslo_log import log
import redis

LOG = log.getLogger(__name__)


class RedisDbDriver(db_api.DbApi):
    redis_mgt = RedisMgt()

    def __init__(self):
        super(RedisDbDriver, self).__init__()
        self.client = {}
        self.remote = []
# need realize connection to DBcluster,record DB Cluster Slot

    def initialize(self, db_ip, db_port, **args):
        # get remote ip port list
        RedisDbDriver.redis_mgt.init_default_node(db_ip, db_port)
        RedisDbDriver.redis_mgt.get_cluster_topology()
        self.remote = RedisDbDriver.redis_mgt.get_master_list()
        for i in range(len(self.remote)):
            ip_port = self.remote[i]['ip_port'].split(':')
            self.client[self.remote[i]['ip_port']] = \
                redis.client.StrictRedis(host=ip_port[0], port=ip_port[1])

    @staticmethod
    def get_redis_mgt():
        return RedisDbDriver.redis_mgt

    def support_publish_subscribe(self):
        return True

    # return nil is not found
    def get_key(self, table, key, topic=None):
        if topic is None:
            res = []
            local_key = self.uuid_to_key(table, key, '*')
            try:
                ip_port = RedisDbDriver.redis_mgt.get_node_by_key(local_key)
                local_keys = self.client[ip_port].keys(local_key)
                if local_keys is None:
                    raise df_exceptions.DBKeyNotFound(key=local_key)
                for i in range(len(local_keys)):
                    res.append(self.client[ip_port].get(local_keys[i]))
                return res
            except Exception as e:
                LOG.erro("exception %s keys %s" % e % local_key)
                raise df_exceptions.DBKeyNotFound(key=local_key)
        else:
            local_key = self.uuid_to_key(table, key, topic)
            try:
                ip_port = RedisDbDriver.redis_mgt.get_node_by_key(local_key)
                if self.client[ip_port] is None:
                    raise df_exceptions.DBKeyNotFound(key=local_key)
                return self.client[ip_port].get(local_key)
            except Exception as e:
                LOG.erro("exception %s keys %s" % e % local_key)
                raise df_exceptions.DBKeyNotFound(key=local_key)

    def set_key(self, table, key, value, topic=None):
        local_key = self.uuid_to_key(table, key, topic)
        try:
            ip_port = RedisDbDriver.redis_mgt.get_node_by_key(local_key)
            if self.client[ip_port] is None:
                raise df_exceptions.DBKeyNotFound(key=local_key)
            res = self.client[ip_port].set(local_key, value)
            if not res:
                self.client[ip_port].delete(local_key)
            return res
        except Exception as e:
            LOG.erro("exception %s keys %s" % e % local_key)
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def create_key(self, table, key, value, topic=None):
        local_key = self.uuid_to_key(table, key, topic)
        try:
            ip_port = RedisDbDriver.redis_mgt.get_node_by_key(local_key)
            if self.client[ip_port] is None:
                raise df_exceptions.DBKeyNotFound(key=local_key)
            res = self.client[ip_port].set(local_key, value)
            if not res:
                self.client[ip_port].delete(local_key)
            return res
        except Exception as e:
            LOG.erro("exception %s keys %s" % e % local_key)
            raise df_exceptions.DBKeyNotFound(key=local_key)

    # return 0 means not found
    def delete_key(self, table, key, topic=None):
        if topic is None:
            local_key = self.uuid_to_key(table, key, '*')
            ip_port = RedisDbDriver.redis_mgt.get_node_by_key(local_key)
            local_keys = self.client[ip_port].keys(local_key)
            if local_keys is None:
                raise df_exceptions.DBKeyNotFound(key=local_key)
            for i in range(len(local_keys)):
                self.client[ip_port].delete(local_keys[i])
        else:
            local_key = self.uuid_to_key(table, key, topic)
            try:
                ip_port = RedisDbDriver.redis_mgt.get_node_by_key(local_key)
                if self.client[ip_port] is None:
                    raise df_exceptions.DBKeyNotFound(key=local_key)
                return self.client[ip_port].delete(local_key)
            except Exception as e:
                LOG.erro("exception %s keys %s" % e % local_key)
                raise df_exceptions.DBKeyNotFound(key=local_key)

    # return nil is not found
    def get_all_entries(self, table, topic=None):
        res = []
        if topic is None:
            local_key = self.uuid_to_key(table, '*', '*')
        else:
            local_key = self.uuid_to_key(table, '*', topic)
        try:
            ip_port = RedisDbDriver.redis_mgt.get_node_by_key(local_key)
            local_keys = self.client[ip_port].keys(local_key)
            if local_keys is None:
                raise df_exceptions.DBKeyNotFound(key=local_key)
            for i in range(len(local_keys)):
                res.append(self.client[ip_port].get(local_keys[i]))
            return res
        except Exception as e:
            LOG.erro("exception %s keys %s" % e % local_key)
            raise df_exceptions.DBKeyNotFound(key=local_key)

    def get_all_keys(self, table, topic=None):
        pass

    def _allocate_unique_key(self):
        pass

    def allocate_unique_key(self):
        pass

        # no need to realize
    def register_notification_callback(self, callback, topics=None):
        pass

    def uuid_to_key(self, table, key, topic):
        if topic is None:
            local_key = ('{' + table + '.' + '*' + '}' + '.' + key)
            LOG.erro("keys %s" % local_key)
            raise df_exceptions.DBKeyNotFound(key=local_key)
        else:
            local_key = ('{' + table + '.' + topic + '}' + '.' + key)
        return local_key

    def check_connection(self, ip_port):
        try:
            if self.client[ip_port] is None:
                raise redis.exceptions.ConnectionError
            self.client[ip_port].get(None)
        except (redis.exceptions.ConnectionError,
                redis.exceptions.BusyLoadingError):
            return False
        return True

    def register_topic_for_notification(self, topic):
        pass

    def unregister_topic_for_notification(self, topic):
        pass
