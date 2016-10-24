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

from cassandra import cluster
from cassandra import policies
from cassandra import query

from oslo_log import log

from dragonflow._i18n import _LE
from dragonflow.common import exceptions as df_exceptions
from dragonflow import conf as cfg
from dragonflow.db import db_api

LOG = log.getLogger(__name__)

ROOT_KS = 'openstack'

CAS_TABLE = 'unique_key'

# NOTE(nick-ma-z): http://datastax.github.io/python-driver/
# api/cassandra.html
CONSISTENCY_MAPPING = {
    'any': query.ConsistencyLevel.ANY,
    'one': query.ConsistencyLevel.ONE,
    'two': query.ConsistencyLevel.TWO,
    'three': query.ConsistencyLevel.THREE,
    'quorum': query.ConsistencyLevel.QUORUM,
    'all': query.ConsistencyLevel.ALL,
    'local_quorum': query.ConsistencyLevel.LOCAL_QUORUM,
    'each_quorum': query.ConsistencyLevel.EACH_QUORUM,
    'serial': query.ConsistencyLevel.SERIAL,
    'local_serial': query.ConsistencyLevel.LOCAL_SERIAL,
    'local_one': query.ConsistencyLevel.LOCAL_ONE,
}


def _check_valid_host(host_str):
    return ':' in host_str and host_str[-1] != ':'


def _parse_hosts(hosts):
    ips = []
    ports = []
    for host_str in hosts:
        if _check_valid_host(host_str):
            host_port = host_str.strip().split(':')
            ips.append(host_port[0])
            port = int(host_port[1])
            ports.append(port)
            if len(ports) > 0 and port not in ports:
                raise df_exceptions.InvalidDBHostConfiguration(host=host_str)
        else:
            LOG.error(_LE("The host string %s is invalid."), host_str)
    return (ips, ports[0])


class CassandraDbDriver(db_api.DbApi):

    def __init__(self):
        super(CassandraDbDriver, self).__init__()
        self.client = None
        self.config = cfg.CONF.df_cassandra

    def _get_consistency_level(self, consistency_level):
        if consistency_level in CONSISTENCY_MAPPING:
            return CONSISTENCY_MAPPING[consistency_level]
        else:
            # by default
            return query.ConsistencyLevel.ONE

    def _get_loadbalancing_policy(self, policy):
        # NOTE(nick-ma-z): http://datastax.github.io/python-driver/
        # api/cassandra/policies.html
        if policy == 'rr':
            return policies.RoundRobinPolicy()
        elif policy == 'dc_rr':
            return policies.DCAwareRoundRobinPolicy(
                cfg.CONF.df_cassandra.local_dc_name,
                cfg.CONF.df_cassandra.used_hosts_per_remote_dc)
        elif policy == 'wl_rr':
            return policies.WhiteListRoundRobinPolicy(
                cfg.CONF.df_cassandra.whitelist_hosts)
        elif policy == 'token_rr':
            return policies.TokenAwarePolicy(
                policies.RoundRobinPolicy())
        else:
            # by default
            return policies.RoundRobinPolicy()

    def initialize(self, db_ip, db_port, **args):
        ips, default_port = _parse_hosts(args['config'].remote_db_hosts)
        lb_policy = self._get_loadbalancing_policy(
            self.config.load_balancing)
        consistency = self._get_consistency_level(
            self.config.consistency_level)

        self.client = cluster.Cluster(ips, port=default_port,
                                      load_balancing_policy=lb_policy)
        self.session = self.client.connect(ROOT_KS)
        self.session.default_consistency_level = consistency
        self.session.row_factory = query.dict_factory

    def support_publish_subscribe(self):
        return False

    def create_table(self, table):
        self.session.execute("CREATE TABLE IF NOT EXISTS %s "
                             "(key text PRIMARY KEY, value text);" % table)

    def delete_table(self, table):
        self.session.execute("DROP TABLE %s;" % table)

    def get_key(self, table, key, topic=None):
        try:
            rows = self.session.execute("SELECT value FROM %(table)s WHERE "
                                        "key='%(key)s';" % {'table': table,
                                                            'key': key})
            return rows[0]['value']
        except Exception:
            raise df_exceptions.DBKeyNotFound(key=key)

    def set_key(self, table, key, value, topic=None):
        self.session.execute("UPDATE %(table)s SET value='%(value)s' WHERE "
                             "key='%(key)s';" % {'table': table,
                                                 'key': key,
                                                 'value': value})

    def create_key(self, table, key, value, topic=None):
        self.session.execute("INSERT INTO %(table)s (key,value) VALUES "
                             "('%(key)s','%(value)s') "
                             "IF NOT EXISTS;" % {'table': table,
                                                 'key': key,
                                                 'value': value})

    def delete_key(self, table, key, topic=None):
        try:
            self.session.execute("DELETE FROM %(table)s WHERE "
                                 "key='%(key)s';" % {'table': table,
                                                     'key': key})
        except Exception:
            raise df_exceptions.DBKeyNotFound(key=key)

    def get_all_entries(self, table, topic=None):
        res = []
        try:
            rows = self.session.execute("SELECT value FROM %s;" % table)
        except Exception:
            return res
        for entry in rows:
            if entry['value']:
                res.append(entry['value'])
        return res

    def get_all_keys(self, table, topic=None):
        res = []
        try:
            rows = self.session.execute("SELECT key FROM %s;" % table)
        except Exception:
            raise df_exceptions.DBKeyNotFound(key=table)
        for entry in rows:
            res.append(entry['key'])
        return res

    def _allocate_unique_key(self, table):
        orig_val = 0
        try:
            orig_val = int(self.get_key(CAS_TABLE, table))
            prev_val = str(orig_val)
            post_val = str(orig_val + 1)
            self.session.execute("UPDATE %(table)s SET value='%(post)s' "
                                 "WHERE key=%(key)s "
                                 "IF value='%(prev)s';" % {'table': CAS_TABLE,
                                                           'post': post_val,
                                                           'key': table,
                                                           'prev': prev_val})
            return orig_val + 1
        except Exception:
            self.create_key(CAS_TABLE, table, "1")
            return 1

    def allocate_unique_key(self, table):
        while True:
            try:
                return self._allocate_unique_key(table)
            except Exception:
                pass

    def register_notification_callback(self, callback):
        pass

    def register_topic_for_notification(self, topic):
        pass

    def unregister_topic_for_notification(self, topic):
        pass

    def process_ha(self):
        pass

    def set_neutron_server(self, is_neutron_server):
        pass
