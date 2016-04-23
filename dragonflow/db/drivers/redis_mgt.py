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


from dragonflow._i18n import _LI, _LE, _LW
from dragonflow.common import utils as df_utils
from dragonflow.db.db_common import DbUpdate
from dragonflow.db.drivers import redis_calckey


import eventlet

from oslo_log import log
from oslo_serialization import jsonutils


import random
import redis
import string

LOG = log.getLogger(__name__)


class RedisMgt(object):

    redisMgt = {}

    def __init__(self):
        super(RedisMgt, self).__init__()
        self.default_node = None
        self.cluster_nodes = {}
        self.cluster_slots = None
        self.calc_key = redis_calckey.key2slot
        self.master_list = []
        self.daemon = df_utils.DFDaemon()
        self.db_callback = None
        self.db_recover_callback = None

    @staticmethod
    def get_instance(ip, port):
        ip_port = RedisMgt.make_host(ip, port)
        if ip_port not in RedisMgt.redisMgt:
            RedisMgt.redisMgt[ip_port] = RedisMgt()
            r = RedisMgt.redisMgt[ip_port]
            r.init_default_node(ip, port)
            r.cluster_nodes = r._get_cluster_nodes(r.default_node)
            r.master_list = r._parse_to_masterlist()
            r.release_default_node()

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

    def _init_node(self, host, port):
        node = redis.StrictRedis(host, port)
        RedisMgt.check_connection(node)
        return node

    def release_default_node(self):
        try:
            self.default_node.connection_pool.get_connection(None, None).\
                disconnect()
            self.default_node.connection_pool.reset()
        except Exception as e:
            LOG.exception(_LE("exception happened "
                              "when release default node, %(e)s")
                          % {'e': e})

    def _release_node(self, node):
        node.connection_pool.get_connection(None, None).disconnect()

    # def read_cluster_topology(self):
    #     self.cluster_nodes = self._get_cluster_nodes(self.default_node)
    #     self.master_list = self._parse_to_masterlist()

    def _parse_node_line(self, line):
        line_items = line.split(' ')
        ret = line_items[:8]
        slots = [sl.split('-') for sl in line_items[8:]]
        ret.append(slots)

        return ret

    def get_cluster_topology_by_all_nodes(self):
        # get redis cluster topology from local nodes cached in initialization
        new_nodes = {}
        for host, info in self.cluster_nodes.items():
            ip_port = host.split(':')
            try:
                node = self._init_node(ip_port[0], ip_port[1])
                info = self._get_cluster_info(node)
                if info['cluster_state'] != 'ok':
                    LOG.warning(_LW("redis cluster state failed"))
                else:
                    new_nodes = self._get_cluster_nodes(node)

                self._release_node(node)
                break
            except Exception:
                LOG.exception(_LE("exception happened "
                                  "when get cluster topology, %(ip)s:"
                                  "%(port)s")
                              % {'ip': ip_port[0], 'port': ip_port[1]})

        return new_nodes

    def _get_cluster_info(self, node):
        raw = node.execute_command('cluster info')

        def _split(line):
            k, v = line.split(':')
            yield k
            yield v

        return {k: v for k, v in
                [_split(line) for line in raw.split('\r\n') if line]}

    def _get_cluster_nodes(self, node):
        raw = node.execute_command('cluster nodes')
        ret = {}

        for line in raw.split('\n'):
            if not line:
                continue

            node_id, ip_port, flags, master_id, ping, pong, epoch, \
                status, slots = self._parse_node_line(line)
            role = flags

            if ',' in flags:
                if "fail" in flags:
                    continue
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
    def make_host(host, port):
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

    def remove_node_from_master_list(self, ip_port):
        if ip_port is not None:
            # remove the node by ip_port
            LOG.info(_LI("remove node %(ip_port)s from "
                         "redis master list")
                     % {'ip_port': ip_port})
            self.master_list = [node for node in self.master_list
                                if node['ip_port'] != ip_port]

    def pubsub_select_node_idx(self):
        db_instance_id = RedisMgt._gen_random_str()
        master_num = len(self.master_list)
        if 0 == master_num:
            return None
        num = hash(db_instance_id) % master_num
        ip_port = self.master_list[num]['ip_port']

        return ip_port

    # check if cluster topo changed
    def _check_nodes_change(self, old_nodes, new_nodes):
        changed = False

        if len(old_nodes) < len(new_nodes):
            changed = True
        elif len(old_nodes) == len(new_nodes):
            cnt = 0
            if 0 == len(old_nodes) and 0 == len(new_nodes):
                changed = False

            for host, info in old_nodes.items():
                for new_host, new_info in new_nodes.items():
                    if host == new_host and info['role'] == \
                            new_info['role']:
                        cnt += 1
                        break

            if cnt != len(old_nodes):
                changed = True
        else:
            # This scenario can be considerd as en exception and
            # should be recovered by people. Assumed that no scale down in
            # cluster.
            # Do not have to notify changes.
            LOG.warning(_LW("redis cluster nodes less than local, "
                            "maybe there is a partition in db "
                            "cluster"))

        return changed

    def redis_failover_callback(self, new_nodes):
        # To receive the NB HA message
        changed = self._check_nodes_change(self.cluster_nodes, new_nodes)

        if changed:
            # update local nodes
            self.cluster_nodes = new_nodes
            self.master_list = self._parse_to_masterlist()

            # send restart message
            if self._check_master_nodes_connection():
                if self.db_callback is not None:
                    self.db_callback(None, None, 'dbrestart', None, None)
                elif self.db_recover_callback is not None:
                    self.db_recover_callback()

    def register_ha_topic(self):
        if self.subscriber is not None:
            self.subscriber.register_topic('redis')

    def set_publisher(self, pub, callback):
        self.db_recover_callback = callback
        self.publisher = pub

    def set_subscriber(self, sub, callback):
        self.db_callback = callback
        self.subscriber = sub

    def daemonize(self):
        self.daemon.daemonize(self.run)

    def _check_master_nodes_connection(self):
        try:
            for remote in self.get_master_list():
                remote_ip_port = remote['ip_port']
                ip_port = remote_ip_port.split(':')
                node = redis.StrictRedis(ip_port[0], ip_port[1])
                RedisMgt.check_connection(node)
                self._release_node(node)
            return True
        except Exception:
            LOG.exception(_LE("check master nodes connection failed"))
            return False

    def run(self):
        while True:
            # read cluster topology every 5 sec
            eventlet.sleep(5)
            try:
                nodes = self.get_cluster_topology_by_all_nodes()
                if len(nodes) > 0:
                    nodes_json = jsonutils.dumps(nodes)
                    update = DbUpdate('ha', 'nodes', 'set', nodes_json,
                                      topic='redis')
                    if self.publisher is not None:
                        self.publisher.send_event(update)

                    # process new nodes got
                    self.redis_failover_callback(nodes)

            except Exception as e:
                LOG.exception(_LE("exception happened "
                                  "when receive messages from plugin, "
                                  "%(e)s") % {'e': e})
