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

from oslo_config import cfg
from dragonflow.common import common_params

import redis
from collections import defaultdict

from oslo_log import log
from ctypes import *
import string
import random
import redis_calckey

LOG = log.getLogger(__name__)

cfg.CONF.register_opts(common_params.df_opts, 'df')

class RedisMgt(object):

    def __init__(self):
        super(RedisMgt, self).__init__()
        self.default_node = None
        self.cluster_nodes = None
        self.cluster_slots = None
        self.calc_key = redis_calckey.keyslot
        self.local_ip = cfg.CONF.df.local_ip
        self.master_list = []
        self.so_path = 'calckey.so'
        self.random_str = RedisMgt._gen_random_str()

    def _load_so(self):
        try:
            lib = cdll.LoadLibrary(self.so_path)
            self.calc_key = lib.HASH_SLOT
            self.calc_key.restype = c_int
            self.calc_key.argtypes = [c_char_p, c_int]
        except OSError as e:
            LOG.warning(e)

    def check_connection(self, rc):
        rc.ping()

    @staticmethod
    def _gen_random_str():
        salt = ''.join(random.sample(string.ascii_letters + string.digits, 8))
        return salt

    def init_default_node(self, host, port):
        try:
            self.default_node = redis.StrictRedis(host, port)
            self.check_connection(self.default_node)
        except Exception as e:
            LOG.warning(e)

    def get_cluster_topology(self):
        self.cluster_nodes = self.nodes()
        self.master_list = self._parse_to_masterlist()
        LOG.info(self.master_list)

    def _parse_node_line(self, line):
        line_items = line.split(' ')
        ret = line_items[:8]
        slots = [sl.split('-') for sl in line_items[8:]]
        ret.append(slots)

        return ret

    def nodes(self):
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

    def slots(self):
        slots_info = self.default_node.execute_command('cluster slots')
        master_slots = defaultdict(list)
        slave_slots = defaultdict(list)

        for item in slots_info:
            master_ip, master_port = item[2]
            slots = [item[0], item[1]]
            master_host = master_ip
            master_slots[self._make_host(master_host, master_port)].append(slots)
            slaves = item[3:]

            for slave_ip, slave_port in slaves:
                slave_host = slave_ip
                slave_slots[self._make_host(slave_host, slave_port)].append(slots)

        return {
            'master': master_slots,
            'slave': slave_slots
        }

    def key_to_slot(self, key):
        return self.calc_key(key, len(key))

    def assign_to_node(self, key):
        slot = self.key_to_slot(key)
        ip_port = None
        for node in self.master_list:
            if node['slot'][0] < slot and slot < node['slot'][1]:
                ip_port = node['ip_port']
                break

        return ip_port

    def _parse_to_masterlist(self):
        list = []
        for host, info in self.cluster_nodes.items():
            if 'master' == info['role']:
                tmp = {
                    'ip_port' : host,
                    'slot' : map(int, info['slots'][0])
                }
                list.append(tmp)

        return list

    def get_master_list(self):
        return self.master_list

    def get_master_nodes_num(self):
        return len(self.master_list)

    def pubsub_select_node(self):
        LOG.info(self.random_str)
        num = hash(self.random_str)%self.get_master_nodes_num()
        ip_port = self.master_list[num]['ip_port']

        return ip_port