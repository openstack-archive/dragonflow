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
from oslo_log import log
import random
import redis
import redis_calckey
import string

LOG = log.getLogger(__name__)


class RedisMgt(object):

    def __init__(self):
        super(RedisMgt, self).__init__()
        self.default_node = None
        self.cluster_nodes = None
        self.cluster_slots = None
        self.calc_key = redis_calckey.key2slot
        self.master_list = []
        self.random_str = RedisMgt._gen_random_str()

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

    def get_cluster_topology(self):
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

    def _make_host(self, host, port):
        return '%s:%s' % (host, port)

    def _key_to_slot(self, key):
        return self.calc_key(key)

    def get_ip_by_key(self, key):
        slot = self._key_to_slot(key)
        ip_port = None
        for node in self.master_list:
            if node['slot'][0] <= slot <= node['slot'][1]:
                ip_port = node['ip_port']
                break

        return ip_port

    def _parse_to_masterlist(self):
        master_list = []
        for host, info in self.cluster_nodes.items():
            if 'master' == info['role']:
                tmp = {
                    'ip_port': host,
                    'slot': map(int, info['slots'][0])
                }
                master_list.append(tmp)

        return master_list

    def get_master_list(self):
        return self.master_list

    def get_master_nodes_num(self):
        return len(self.master_list)

    def pubsub_select_node(self):
        num = hash(self.random_str) % self.get_master_nodes_num()
        ip_port = self.master_list[num]['ip_port']

        return ip_port
