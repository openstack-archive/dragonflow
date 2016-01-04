# Copyright (c) 2015 OpenStack Foundation.
#
# All Rights Reserved.
#
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
import eventlet
import netaddr
import time

from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from neutron.i18n import _LI

from dragonflow.db import db_publisher
from dragonflow.db import db_subscriber

eventlet.monkey_patch()

LOG = log.getLogger(__name__)


class DbUpdate(object):
    """Encapsulates a DB update

    An instance of this object carries the information necessary to prioritize
    and process a request to update a DB entry.
    Lower value is higher priority !
    """
    def __init__(self, table, key, action, value, priority=5,
                 timestamp=None):
        self.priority = priority
        self.timestamp = timestamp
        if not timestamp:
            self.timestamp = timeutils.utcnow()
        self.key = key
        self.action = action
        self.table = table
        self.value = value

    def to_array(self):
        return [self.table, self.key, self.action, self.value]

    def __str__(self):
        return"Action:%s, Value:%s" % (self.action, self.value)

    def __lt__(self, other):
        """Implements priority among updates

        Lower numerical priority always gets precedence.  When comparing two
        updates of the same priority then the one with the earlier timestamp
        gets procedence.  In the unlikely event that the timestamps are also
        equal it falls back to a simple comparison of ids meaning the
        precedence is essentially random.
        """
        if self.priority != other.priority:
            return self.priority < other.priority
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        return self.key < other.key


class NbApi(object):

    def __init__(self, db_driver, use_pubsub=False, is_plugin=False):
        super(NbApi, self).__init__()
        self.driver = db_driver
        self.controller = None
        self._queue = eventlet.queue.PriorityQueue()
        self.db_apply_failed = False
        self.use_pubsub = use_pubsub
        self.publiser = None
        self.is_plugin = is_plugin

    def initialize(self, db_ip='127.0.0.1', db_port=4001):
        self.driver.initialize(db_ip, db_port, config=cfg.CONF.df)
        if self.use_pubsub:
            if self.is_plugin:
                #TODO(gampel) Move plugin publish_port and
                #controller port to conf settings
                self.publiser = db_publisher.PublisherAgent(
                                            db_ip,
                                            self.is_plugin,
                                            publish_port=8866)
                self.publiser.daemonize()
            else:
                self.publiser = db_publisher.PublisherAgent(
                                            db_ip,
                                            is_plugin=self.is_plugin,
                                            publish_port=8867)

                self.subscriber = db_subscriber.SubscriberAgent(
                                                db_ip,
                                                self.db_change_callback,
                                                plugin_port=8866,
                                                cont_port=8867)
                #NOTE(gampel) we want to start queuing event as soon
                #as possible
                self.subscriber.daemonize()

    def support_publish_subscribe(self):
        if self.use_pubsub:
            return True
        return self.driver.support_publish_subscribe()

    def _send_db_change_event(self, table, key, action, value):
        if self.use_pubsub:
            update = DbUpdate(table, key, action, value)
            self.publiser.send_event(update)
            eventlet.sleep(0)

    def allocate_tunnel_key(self):
        return self.driver.allocate_unique_key()

    def register_notification_callback(self, controller):
        self.controller = controller
        LOG.info(_LI("DB configuration sync finished, waiting for changes"))
        if not self.use_pubsub:
            self.driver.register_notification_callback(
                self.db_change_callback)
        self._read_db_changes_from_queue()

    def db_change_callback(self, table, key, action, value):
        update = DbUpdate(table, key, action, value)
        LOG.info(_LI("Pushing Update to Queue: %s"), update)
        self._queue.put(update)
        eventlet.sleep(0)

    def _read_db_changes_from_queue(self):
        while True:
            if not self.db_apply_failed:
                self.next_update = self._queue.get(block=True)
                LOG.info(_LI("Event update: %s"),
                        self.next_update)
            try:
                self.apply_db_change(self.next_update.table,
                                     self.next_update.key,
                                     self.next_update.action,
                                     self.next_update.value)
                self.db_apply_failed = False
                self._queue.task_done()
            except Exception as e:
                if "ofport is 0" not in e.message:
                    LOG.warning(e)
                self.db_apply_failed = True
                time.sleep(1)

    def apply_db_change(self, table, key, action, value):
        if action == 'sync':
            self.controller.run_sync()
            return
        self.controller.vswitch_api.sync()
        if 'lport' == table:
            if action == 'set' or action == 'create':
                lport = LogicalPort(value)
                self.controller.logical_port_updated(lport)
            else:
                lport_id = key
                self.controller.logical_port_deleted(lport_id)
        if 'lrouter' == table:
            if action == 'set' or action == 'create':
                lrouter = LogicalRouter(value)
                self.controller.router_updated(lrouter)
            else:
                lrouter_id = key
                self.controller.router_deleted(lrouter_id)
        if 'chassis' == table:
            if action == 'set' or action == 'create':
                chassis = Chassis(value)
                self.controller.chassis_created(chassis)
            else:
                chassis_id = key
                self.controller.chassis_deleted(chassis_id)
        if 'lswitch' == table:
            if action == 'set' or action == 'create':
                lswitch = LogicalSwitch(value)
                self.controller.logical_switch_updated(lswitch)
            else:
                lswitch_id = key
                self.controller.logical_switch_deleted(lswitch_id)

    def sync(self):
        pass

    def create_security_group(self, name, **columns):
        secgroup = {}
        secgroup['name'] = name
        for col, val in columns.items():
            secgroup[col] = val
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.create_key('secgroup', name, secgroup_json)
        self._send_db_change_event('secgroup', name, 'create', secgroup_json)

    def delete_security_group(self, name):
        self.driver.delete_key('secgroup', name)
        self._send_db_change_event('secgroup', name, 'delete', name)

    def add_security_group_rules(self, sg_name, new_rules):
        secgroup_json = self.driver.get_key('secgroup', sg_name)
        secgroup = jsonutils.loads(secgroup_json)
        rules = secgroup.get('rules', [])
        rules.extend(new_rules)
        secgroup['rules'] = rules
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.set_key('secgroup', sg_name, secgroup_json)
        self._send_db_change_event('secgroup', sg_name, 'set', secgroup_json)

    def delete_security_group_rule(self, sg_name, sgr_id):
        secgroup_json = self.driver.get_key('secgroup', sg_name)
        secgroup = jsonutils.loads(secgroup_json)
        rules = secgroup.get('rules')
        new_rules = []
        for rule in rules:
            if rule['id'] != sgr_id:
                new_rules.append(rule)
        secgroup['rules'] = new_rules
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.set_key('secgroup', sg_name, secgroup_json)
        self._send_db_change_event('secgroup', sg_name, 'set', secgroup_json)

    def get_chassis(self, name):
        try:
            chassis_value = self.driver.get_key('chassis', name)
            return Chassis(chassis_value)
        except Exception:
            return None

    def get_all_chassis(self):
        res = []
        for entry_value in self.driver.get_all_entries('chassis'):
            res.append(Chassis(entry_value))
        return res

    def add_chassis(self, name, ip, tunnel_type):
        chassis = {'name': name, 'ip': ip,
                   'tunnel_type': tunnel_type}
        chassis_json = jsonutils.dumps(chassis)
        self.driver.create_key('chassis', name, chassis_json)
        self._send_db_change_event('chassis', name, 'create', chassis_json)

    def get_lswitch(self, name):
        try:
            lswitch_value = self.driver.get_key('lswitch', name)
            return LogicalSwitch(lswitch_value)
        except Exception:
            return None

    def add_subnet(self, id, lswitch_name, **columns):
        lswitch_json = self.driver.get_key('lswitch', lswitch_name)
        lswitch = jsonutils.loads(lswitch_json)

        subnet = {}
        subnet['id'] = id
        subnet['lswitch'] = lswitch_name
        for col, val in columns.items():
            subnet[col] = val

        subnets = lswitch.get('subnets', [])
        subnets.append(subnet)
        lswitch['subnets'] = subnets
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', lswitch_name, lswitch_json)
        self._send_db_change_event('lswitch', lswitch_name, 'set',
                                   lswitch_json)

    def update_subnet(self, id, lswitch_name, **columns):
        lswitch_json = self.driver.get_key('lswitch', lswitch_name)
        lswitch = jsonutils.loads(lswitch_json)
        subnet = None
        for s in lswitch.get('subnets', []):
            if s['id'] == id:
                subnet = s

        for col, val in columns.items():
            subnet[col] = val

        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', lswitch_name, lswitch_json)
        self._send_db_change_event('lswitch', lswitch_name, 'set',
                                   lswitch_json)

    def delete_subnet(self, id, lswitch_name):
        lswitch_json = self.driver.get_key('lswitch', lswitch_name)
        lswitch = jsonutils.loads(lswitch_json)

        new_ports = []
        for subnet in lswitch.get('subnets', []):
            if subnet['id'] != id:
                new_ports.append(subnet)

        lswitch['subnets'] = new_ports
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', lswitch_name, lswitch_json)
        self._send_db_change_event('lswitch', lswitch_name, 'set',
                                   lswitch_json)

    def get_logical_port(self, port_id):
        try:
            port_value = self.driver.get_key('lport', port_id)
            return LogicalPort(port_value)
        except Exception:
            return None

    def get_all_logical_ports(self):
        res = []
        for lport_value in self.driver.get_all_entries('lport'):
            lport = LogicalPort(lport_value)
            if lport.get_chassis() is None:
                continue
            res.append(lport)
        return res

    def create_lswitch(self, name, **columns):
        lswitch = {}
        lswitch['name'] = name
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.create_key('lswitch', name, lswitch_json)
        self._send_db_change_event('lswitch', name, 'create', lswitch_json)

    def update_lswitch(self, name, **columns):
        self._send_db_change_event('lswitch', 'name', 'set', 'lswitch_json')

        lswitch_json = self.driver.get_key('lswitch', name)
        lswitch = jsonutils.loads(lswitch_json)
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', name, lswitch_json)
        self._send_db_change_event('lswitch', name, 'set', lswitch_json)

    def delete_lswitch(self, name):
        self.driver.delete_key('lswitch', name)
        self._send_db_change_event('lswitch', name, 'delete', name)

    def create_lport(self, name, lswitch_name, **columns):
        lport = {}
        lport['name'] = name
        lport['lswitch'] = lswitch_name
        for col, val in columns.items():
            lport[col] = val
        lport_json = jsonutils.dumps(lport)
        self.driver.create_key('lport', name, lport_json)
        self._send_db_change_event('lport', name, 'create', lport_json)

    def update_lport(self, name, **columns):
        lport_json = self.driver.get_key('lport', name)
        lport = jsonutils.loads(lport_json)
        for col, val in columns.items():
            lport[col] = val
        lport_json = jsonutils.dumps(lport)
        self.driver.set_key('lport', name, lport_json)
        self._send_db_change_event('lport', name, 'set', lport_json)

    def delete_lport(self, name):
        self.driver.delete_key('lport', name)
        self._send_db_change_event('lport', name, 'delete', name)

    def create_lrouter(self, name, **columns):
        lrouter = {}
        lrouter['name'] = name
        for col, val in columns.items():
            lrouter[col] = val
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.create_key('lrouter', name, lrouter_json)
        self._send_db_change_event('lrouter', name, 'create', lrouter_json)

    def delete_lrouter(self, name):
        self.driver.delete_key('lrouter', name)
        self._send_db_change_event('lrouter', name, 'delete', name)

    def add_lrouter_port(self, name, lrouter_name, lswitch, **columns):
        lrouter_json = self.driver.get_key('lrouter', lrouter_name)
        lrouter = jsonutils.loads(lrouter_json)

        lrouter_port = {}
        lrouter_port['name'] = name
        lrouter_port['lrouter'] = lrouter_name
        lrouter_port['lswitch'] = lswitch
        for col, val in columns.items():
            lrouter_port[col] = val

        router_ports = lrouter.get('ports', [])
        router_ports.append(lrouter_port)
        lrouter['ports'] = router_ports
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.set_key('lrouter', lrouter_name, lrouter_json)
        self._send_db_change_event('lrouter', lrouter_name, 'set',
                                   lrouter_json)

    def delete_lrouter_port(self, lrouter_name, lswitch):
        lrouter_json = self.driver.get_key('lrouter', lrouter_name)
        lrouter = jsonutils.loads(lrouter_json)

        new_ports = []
        for port in lrouter.get('ports', []):
            if port['lswitch'] != lswitch:
                new_ports.append(port)

        lrouter['ports'] = new_ports
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.set_key('lrouter', lrouter_name, lrouter_json)
        self._send_db_change_event('lrouter', lrouter_name, 'set',
                                   lrouter_json)

    def get_routers(self):
        res = []
        for lrouter_value in self.driver.get_all_entries('lrouter'):
            res.append(LogicalRouter(lrouter_value))
        return res

    def get_all_logical_switches(self):
        res = []
        for lswitch_value in self.driver.get_all_entries('lswitch'):
            res.append(LogicalSwitch(lswitch_value))
        return res


class Chassis(object):

    def __init__(self, value):
        self.chassis = jsonutils.loads(value)

    def get_name(self):
        return self.chassis['name']

    def get_ip(self):
        return self.chassis['ip']

    def get_encap_type(self):
        return self.chassis['tunnel_type']

    def __str__(self):
        return self.chassis.__str__()


class LogicalSwitch(object):

    def __init__(self, value):
        self.lswitch = jsonutils.loads(value)

    def get_id(self):
        return self.lswitch['name']

    def get_subnets(self):
        res = []
        for subnet in self.lswitch['subnets']:
            res.append(Subnet(subnet))
        return res

    def __str__(self):
        return self.lswitch.__str__()

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.lswitch == other.lswitch
        else:
            return False


class Subnet(object):

    def __init__(self, value):
        self.subnet = value

    def enable_dhcp(self):
        return self.subnet['enable_dhcp']

    def get_id(self):
        return self.subnet['id']

    def get_dhcp_server_address(self):
        return self.subnet['dhcp_ip']

    def get_cidr(self):
        return self.subnet['cidr']

    def get_gateway_ip(self):
        return self.subnet['gateway_ip']

    def get_dns_name_servers(self):
        return self.subnet['dns_nameservers']


class LogicalPort(object):

    def __init__(self, value):
        self.external_dict = {}
        self.lport = jsonutils.loads(value)

    def get_id(self):
        return self.lport.get('name')

    def get_ip(self):
        return self.lport['ips'][0]

    def get_mac(self):
        return self.lport['macs'][0]

    def get_chassis(self):
        return self.lport.get('chassis')

    def get_lswitch_id(self):
        return self.lport.get('lswitch')

    def get_tunnel_key(self):
        return int(self.lport['tunnel_key'])

    def set_external_value(self, key, value):
        self.external_dict[key] = value

    def get_external_value(self, key):
        return self.external_dict.get(key)

    def get_device_owner(self):
        return self.lport.get('device_owner')

    def __str__(self):
        return self.lport.__str__() + self.external_dict.__str__()


class LogicalRouter(object):

    def __init__(self, value):
        self.lrouter = jsonutils.loads(value)

    def get_name(self):
        return self.lrouter.get('name')

    def get_ports(self):
        res = []
        for port in self.lrouter.get('ports'):
            res.append(LogicalRouterPort(port))
        return res

    def __str__(self):
        return self.lrouter.__str__()


class LogicalRouterPort(object):

    def __init__(self, value):
        self.router_port = value
        self.cidr = netaddr.IPNetwork(self.router_port['network'])

    def get_name(self):
        return self.router_port.get('name')

    def get_ip(self):
        return str(self.cidr.ip)

    def get_cidr_network(self):
        return str(self.cidr.network)

    def get_cidr_netmask(self):
        return str(self.cidr.netmask)

    def get_mac(self):
        return self.router_port.get('mac')

    def get_lswitch_id(self):
        return self.router_port['lswitch']

    def get_network(self):
        return self.router_port['network']

    def get_tunnel_key(self):
        return self.router_port['tunnel_key']

    def __eq__(self, other):
        return self.get_name() == other.get_name()

    def __str__(self):
        return self.router_port.__str__()
