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

from oslo_log import log

from dragonflow._i18n import _LE
from dragonflow.db.drivers import redis_calckey

import random
import redis
import string

LOG = log.getLogger(__name__)


class RedisMgt(object):

    redisMgt = {}

    def __init__(self):
        super(RedisMgt, self).__init__()
        self.default_node = None
        self.cluster_nodes = None
        self.cluster_slots = None
        self.calc_key = redis_calckey.key2slot
        self.master_list = []
        self.db_instance_id = RedisMgt._gen_random_str()
        self.pubsub_node_idx = None

    @staticmethod
    def get_instance(ip, port):
        ip_port = RedisMgt._make_host(ip, port)
        if ip_port not in RedisMgt.redisMgt:
            RedisMgt.redisMgt[ip_port] = RedisMgt()
            r = RedisMgt.redisMgt[ip_port]
            r.init_default_node(ip, port)
            r.read_cluster_topology()
            r.pubsub_node_idx = r.caculate_pubsub_node_idx()

        return RedisMgt.redisMgt[ip_port]

    @staticmethod
    def check_connection(rc):
        rc.ping()

    @staticmethod
    def _gen_random_str():
        salt = ''.join(random.sample(string.ascii_letters + string.digits, 8))
        return salt

    def init_default_node(self, host, port):
        try:
            self.default_node = redis.StrictRedis(host, port)
            RedisMgt.check_connection(self.default_node)
        except Exception as e:
            LOG.exception(_LE("exception happened "
                              "when connect to default node, %s"), e)

    def read_cluster_topology(self):
        self.cluster_nodes = self._get_cluster_nodes()
        self.master_list = self._parse_to_masterlist()

    def _parse_node_line(self, line):
        line_items = line.split(' ')
        ret = line_items[:8]
        slots = [sl.split('-') for sl in line_items[8:]]
        ret.append(slots)

        return ret

    def _get_cluster_nodes(self):
        raw = self.default_node.execute_command('cluster nodes')
        ret = {}

        for line in raw.split('\n'):
            if not line:
                continue

            node_id, ip_port, flags, master_id, ping, pong, epoch, \
                status, slots = self._parse_node_line(line)
            role = flags

            if ',' in flags:
                if "slave" in flags:
                    role = "slave"
                elif "master" in flags:
                    role = "master"

            ret[ip_port] = {
                'node_id': node_id,
                'role': role,
                'master_id': master_id,
                'last_ping_sent': ping,
                'last_pong_rcvd': pong,
                'epoch': epoch,
                'status': status,
                'slots': slots
            }

        return ret

    @staticmethod
    def _make_host(host, port):
        return '%s:%s' % (host, port)

    def _key_to_slot(self, key):
        return self.calc_key(key)

    def get_ip_by_key(self, key):
        slot = self._key_to_slot(key)
        ip_port = None
        for node in self.master_list:
            if len(node['slot']) > 0:
                for each in node['slot']:
                    if len(each) == 1:
                        if slot == each[0]:
                            ip_port = node['ip_port']
                            break
                    else:
                        if each[0] <= slot <= each[1]:
                            ip_port = node['ip_port']
                            break
                if ip_port is not None:
                    break

        return ip_port

    def _parse_to_masterlist(self):
        master_list = []
        for host, info in self.cluster_nodes.items():
            if 'master' == info['role']:
                slots = []
                if len(info['slots']) > 0:
                    for each in info['slots']:
                        slots.append(map(int, each))
                tmp = {
                    'ip_port': host,
                    'slot': slots
                }
                master_list.append(tmp)

        return master_list

    def get_master_list(self):
        return self.master_list

    def get_master_nodes_num(self):
        return len(self.master_list)

    def caculate_pubsub_node_idx(self):
        num = hash(self.db_instance_id) % self.get_master_nodes_num()
        return self.master_list[num]['ip_port']

    def pubsub_select_node_idx(self):
        return self.pubsub_node_idx
