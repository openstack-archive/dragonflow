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

from dragonflow._i18n import _LI
from dragonflow.common import utils as df_utils
from dragonflow.db.db_common import DbUpdate
from dragonflow.db import pub_sub_api

eventlet.monkey_patch()

LOG = log.getLogger(__name__)


class NbApi(object):

    def __init__(self, db_driver, use_pubsub=False, is_neutron_server=False):
        super(NbApi, self).__init__()
        self.driver = db_driver
        self.controller = None
        self._queue = eventlet.queue.PriorityQueue()
        self.db_apply_failed = False
        self.use_pubsub = use_pubsub
        self.publisher = None
        self.is_neutron_server = is_neutron_server
        self.db_table_monitors = None

    def initialize(self, db_ip='127.0.0.1', db_port=4001):
        self.driver.initialize(db_ip, db_port, config=cfg.CONF.df)
        if self.use_pubsub:
            self.publisher = self._get_publisher()
            self.subscriber = self._get_subscriber()
            if self.is_neutron_server:
                #Publisher is part of the neutron server Plugin
                self.publisher.initialize()
                self._start_db_table_monitors()
            else:
                #NOTE(gampel) we want to start queuing event as soon
                #as possible
                self._start_subsciber()

    def _get_publisher(self):
        if cfg.CONF.df.pub_sub_use_multiproc:
            pubsub_driver_name = cfg.CONF.df.pub_sub_multiproc_driver
        else:
            pubsub_driver_name = cfg.CONF.df.pub_sub_driver
        pub_sub_driver = df_utils.load_driver(
                                    pubsub_driver_name,
                                    df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        return pub_sub_driver.get_publisher()

    def _get_subscriber(self):
        pub_sub_driver = df_utils.load_driver(
                                    cfg.CONF.df.pub_sub_driver,
                                    df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        return pub_sub_driver.get_subscriber()

    def _start_db_table_monitors(self):
        self.db_table_monitors = [self._start_db_table_monitor(table_name)
            for table_name in pub_sub_api.MONITOR_TABLES]

    def _start_db_table_monitor(self, table_name):
        table_monitor = pub_sub_api.TableMonitor(
            table_name,
            self.driver,
            self.publisher,
            cfg.CONF.df.monitor_table_poll_time,
        )
        table_monitor.daemonize()
        return table_monitor

    def _stop_db_table_monitors(self):
        if not self.db_table_monitors:
            return
        for monitor in self.db_table_monitors:
            monitor.stop()
        self.db_table_monitors = None

    def _start_subsciber(self):
        self.subscriber.initialize(self.db_change_callback)
        # TODO(oanson) Move publishers_ips to DF DB.
        publishers_ips = cfg.CONF.df.publishers_ips
        for ip in publishers_ips:
            uri = '%s://%s:%s' % (
                cfg.CONF.df.publisher_transport,
                ip,
                cfg.CONF.df.publisher_port
            )
            self.subscriber.register_listen_address(uri)
        self.subscriber.daemonize()

    def support_publish_subscribe(self):
        if self.use_pubsub:
            return True
        return self.driver.support_publish_subscribe()

    def _send_db_change_event(self, table, key, action, value):
        if self.use_pubsub:
            update = DbUpdate(table, key, action, value)
            self.publisher.send_event(update)
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

    def db_change_callback(self, table, key, action, value, topic):
        update = DbUpdate(table, key, action, value, topic=topic)
        LOG.info(_LI("Pushing Update to Queue: %s"), update)
        self._queue.put(update)
        eventlet.sleep(0)

    def _read_db_changes_from_queue(self):
        while True:
            if not self.db_apply_failed:
                self.next_update = self._queue.get(block=True)
                LOG.debug("Event update: %s", self.next_update)
            try:
                value = self.next_update.value
                if not value and self.next_update.action != 'delete':
                    if self.next_update.table and self.next_update.key:
                        value = self.driver.get_key(self.next_update.table,
                                                self.next_update.key)

                self.apply_db_change(self.next_update.table,
                                     self.next_update.key,
                                     self.next_update.action,
                                     value)
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
        if 'secgroup' == table:
            if action == 'set' or action == 'create':
                secgroup = SecurityGroup(value)
                self.controller.security_group_updated(secgroup)
            else:
                secgroup_id = key
                self.controller.security_group_deleted(secgroup_id)
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
        if 'floatingip' == table:
            if action == 'set' or action == 'create':
                floatingip = Floatingip(value)
                self.controller.floatingip_updated(floatingip)
            else:
                floatingip_id = key
                self.controller.floatingip_deleted(floatingip_id)

    def sync(self):
        pass

    def create_security_group(self, name, topic, **columns):
        secgroup = {}
        secgroup['name'] = name
        secgroup['topic'] = topic
        for col, val in columns.items():
            secgroup[col] = val
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.create_key('secgroup', name, secgroup_json)
        self._send_db_change_event('secgroup', name, 'create', secgroup_json)

    def delete_security_group(self, name, topic):
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
        for entry_value in self.driver.get_all_entries('chassis', None):
            res.append(Chassis(entry_value))
        return res

    def add_chassis(self, name, ip, tunnel_type):
        chassis = {'name': name, 'ip': ip,
                   'tunnel_type': tunnel_type}
        chassis_json = jsonutils.dumps(chassis)
        self.driver.create_key('chassis', name, chassis_json)

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

    def get_all_logical_ports(self, topic=None):
        res = []
        for lport_value in self.driver.get_all_entries('lport', topic):
            lport = LogicalPort(lport_value)
            if lport.get_chassis() is None:
                continue
            res.append(lport)
        return res

    def create_lswitch(self, name, topic, **columns):
        lswitch = {}
        lswitch['name'] = name
        lswitch['topic'] = topic
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.create_key('lswitch', name, lswitch_json)
        self._send_db_change_event('lswitch', name, 'create', lswitch_json)

    def update_lswitch(self, name, **columns):
        lswitch_json = self.driver.get_key('lswitch', name)
        lswitch = jsonutils.loads(lswitch_json)
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', name, lswitch_json)
        self._send_db_change_event('lswitch', name, 'set', lswitch_json)

    def delete_lswitch(self, name, topic):
        self.driver.delete_key('lswitch', name)
        self._send_db_change_event('lswitch', name, 'delete', name)

    def create_lport(self, name, lswitch_name, topic, **columns):
        lport = {}
        lport['name'] = name
        lport['lswitch'] = lswitch_name
        lport['topic'] = topic
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

    def delete_lport(self, name, topic):
        self.driver.delete_key('lport', name)
        self._send_db_change_event('lport', name, 'delete', name)

    def create_lrouter(self, name, topic, **columns):
        lrouter = {}
        lrouter['name'] = name
        lrouter['topic'] = topic
        for col, val in columns.items():
            lrouter[col] = val
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.create_key('lrouter', name, lrouter_json)
        self._send_db_change_event('lrouter', name, 'create', lrouter_json)

    def delete_lrouter(self, name, topic):
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

    def get_routers(self, topic=None):
        res = []
        for lrouter_value in self.driver.get_all_entries('lrouter', topic):
            res.append(LogicalRouter(lrouter_value))
        return res

    def get_security_groups(self, topic=None):
        res = []
        for secgroup_value in self.driver.get_all_entries('secgroup', topic):
            res.append(SecurityGroup(secgroup_value))
        return res

    def get_all_logical_switches(self, topic=None):
        res = []
        for lswitch_value in self.driver.get_all_entries('lswitch', topic):
            res.append(LogicalSwitch(lswitch_value))
        return res

    def create_floatingip(self, name, **columns):
        floatingip = {}
        floatingip['name'] = name
        for col, val in columns.items():
            floatingip[col] = val
        floatingip_json = jsonutils.dumps(floatingip)
        self.driver.create_key('floatingip', name, floatingip_json)

    def delete_floatingip(self, name):
        self.driver.delete_key('floatingip', name)

    def update_floatingip(self, name, **columns):
        floatingip_json = self.driver.get_key('floatingip', name)
        floatingip = jsonutils.loads(floatingip_json)
        for col, val in columns.items():
            floatingip[col] = val
        floatingip_json = jsonutils.dumps(floatingip)
        self.driver.set_key('floatingip', name, floatingip_json)

    def get_floatingip(self, name):
        try:
            floatingip_value = self.driver.get_key('floatingip', name)
            return Floatingip(floatingip_value)
        except Exception:
            return None

    def get_floatingips(self):
        res = []
        for floatingip in self.driver.get_all_entries('floatingip'):
            res.append(Floatingip(floatingip))
        return res

    def get_floatingip_by_logical_port(self, port_id):
        for floatingip in self.get_floatingips():
            if port_id == floatingip['port_id']:
                return Floatingip(floatingip)
        return None


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

    def is_distributed(self):
        return self.lrouter.get('distributed', False)

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


class SecurityGroup(object):

    def __init__(self, value):
        self.secgroup = jsonutils.loads(value)

    @property
    def name(self):
        return self.secgroup.get('name')

    @property
    def id(self):
        return self.secgroup.get('id')

    @property
    def rules(self):
        res = []
        for rule in self.secgroup.get('rules'):
            res.append(SecurityGroupRule(rule))
        return res

    def __str__(self):
        return self.secgroup.__str__()


class SecurityGroupRule(object):

    def __init__(self, value):
        self.secrule = value

    @property
    def direction(self):
        return self.secrule['direction']

    @property
    def ethertype(self):
        return self.secrule['ethertype']

    @property
    def id(self):
        return self.secrule['id']

    @property
    def port_range_max(self):
        return self.secrule['port_range_max']

    @property
    def port_range_min(self):
        return self.secrule['port_range_min']

    @property
    def protocol(self):
        return self.secrule['protocol']

    @property
    def remote_group_id(self):
        return self.secrule['remote_group_id']

    @property
    def remote_ip_prefix(self):
        return self.secrule['remote_ip_prefix']

    @property
    def security_group_id(self):
        return self.secrule['security_group_id']

    def __eq__(self, other):
        return self.id == other.id

    def __str__(self):
        return self.secrule.__str__()


class Floatingip(object):

    def __init__(self, value):
        self.floatingip = jsonutils.loads(value)

    def get_name(self):
        return self.floatingip['name']

    def get_floatingip_address(self):
        return self.floatingip['floating_ip_address']

    def get_lport_id(self):
        return self.floatingip['port_id']

    def get_fixed_ip(self):
        return self.floatingip['fixed_ip_address']

    def get_lrouter_id(self):
        return self.floatingip['router_id']

    def __str__(self):
        return self.floatingip.__str__()
