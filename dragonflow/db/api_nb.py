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

import abc
import time

import eventlet
import netaddr
from neutron_lib import constants as const
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
import six

from dragonflow._i18n import _LI, _LW, _LE
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import pub_sub_api

LOG = log.getLogger(__name__)


DB_ACTION_LIST = ['create', 'set', 'delete', 'log',
                  'sync', 'sync_started', 'sync_finished', 'dbrestart']

_nb_api = None


class NbApi(object):

    def __init__(self, db_driver, use_pubsub=False, is_neutron_server=False):
        super(NbApi, self).__init__()
        self.driver = db_driver
        self.controller = None
        self._queue = eventlet.queue.PriorityQueue()
        self.use_pubsub = use_pubsub
        self.publisher = None
        self.subscriber = None
        self.is_neutron_server = is_neutron_server
        self.enable_selective_topo_dist = \
            cfg.CONF.df.enable_selective_topology_distribution

    @staticmethod
    def get_instance(is_neutron_server):
        global _nb_api
        if _nb_api is None:
            nb_driver = df_utils.load_driver(
                cfg.CONF.df.nb_db_class,
                df_utils.DF_NB_DB_DRIVER_NAMESPACE)
            nb_api = NbApi(
                nb_driver,
                use_pubsub=cfg.CONF.df.enable_df_pub_sub,
                is_neutron_server=is_neutron_server)
            nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                              db_port=cfg.CONF.df.remote_db_port)
            _nb_api = nb_api
        return _nb_api

    def initialize(self, db_ip='127.0.0.1', db_port=4001):
        self.driver.initialize(db_ip, db_port, config=cfg.CONF.df)
        if self.use_pubsub:
            self.publisher = self._get_publisher()
            self.subscriber = self._get_subscriber()
            if self.is_neutron_server:
                # Publisher is part of the neutron server Plugin
                self.publisher.initialize()
                # Start a thread to detect DB failover in Plugin
                self.publisher.set_publisher_for_failover(
                    self.publisher,
                    self.db_recover_callback)
                self.publisher.start_detect_for_failover()
            else:
                # NOTE(gampel) we want to start queuing event as soon
                # as possible
                self._start_subsciber()
                # Register for DB Failover detection in NB Plugin
                self.subscriber.set_subscriber_for_failover(
                    self.subscriber,
                    self.db_change_callback)
                self.subscriber.register_hamsg_for_db()

    def db_recover_callback(self):
        # only db with HA func can go in here
        self.driver.process_ha()
        self.publisher.process_ha()
        self.subscriber.process_ha()

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

    def _start_subsciber(self):
        self.subscriber.initialize(self.db_change_callback)
        self.subscriber.register_topic(db_common.SEND_ALL_TOPIC)
        publishers_ips = cfg.CONF.df.publishers_ips
        uris = {'%s://%s:%s' % (
                cfg.CONF.df.publisher_transport,
                ip,
                cfg.CONF.df.publisher_port) for ip in publishers_ips}
        publishers = self.get_publishers()
        uris |= {publisher.get_uri() for publisher in publishers}
        for uri in uris:
            self.subscriber.register_listen_address(uri)
        self.subscriber.daemonize()

    def support_publish_subscribe(self):
        if self.use_pubsub:
            return True
        return self.driver.support_publish_subscribe()

    def _send_db_change_event(self, table, key, action, value, topic):
        if self.use_pubsub:
            if not self.enable_selective_topo_dist:
                topic = db_common.SEND_ALL_TOPIC
            update = db_common.DbUpdate(table, key, action, value, topic=topic)
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

    def db_change_callback(self, table, key, action, value, topic=None):
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        LOG.info(_LI("Pushing Update to Queue: %s"), update)
        self._queue.put(update)
        eventlet.sleep(0)

    def _read_db_changes_from_queue(self):
        sync_rate_limiter = df_utils.RateLimiter(
            max_rate=1, time_unit=db_common.DB_SYNC_MINIMUM_INTERVAL)
        while True:
            self.next_update = self._queue.get(block=True)
            LOG.debug("Event update: %s", self.next_update)
            try:
                value = self.next_update.value
                if (not value and
                        self.next_update.action not in {'delete', 'log',
                                                        'dbrestart'}):
                    if self.next_update.table and self.next_update.key:
                        value = self.driver.get_key(self.next_update.table,
                                                    self.next_update.key)

                self.apply_db_change(self.next_update.table,
                                     self.next_update.key,
                                     self.next_update.action,
                                     value)
            except Exception as e:
                if "ofport is 0" not in e.message:
                    LOG.exception(e)
                if not sync_rate_limiter():
                    self.apply_db_change(None, None, 'sync', None)
            self._queue.task_done()

    def apply_db_change(self, table, key, action, value):
        # determine if the action is allowed or not
        if action not in DB_ACTION_LIST:
            LOG.warning(_LW('Unknown action %(action)s for table '
                            '%(table)s'), {'action': action, 'table': table})
            return

        if action == 'sync':
            self.controller.run_sync()
            return
        elif action == 'dbrestart':
            self.db_recover_callback()
            return

        if 'secgroup' == table:
            if action == 'set' or action == 'create':
                secgroup = SecurityGroup(value)
                self.controller.security_group_updated(secgroup)
            elif action == 'delete':
                secgroup_id = key
                self.controller.security_group_deleted(secgroup_id)
        elif 'lport' == table:
            if action == 'create':
                lport = LogicalPort(value)
                self.controller.logical_port_created(lport)
            elif action == 'set':
                lport = LogicalPort(value)
                self.controller.logical_port_updated(lport)
            elif action == 'delete':
                lport_id = key
                self.controller.logical_port_deleted(lport_id)
        elif 'lrouter' == table:
            if action == 'set' or action == 'create':
                lrouter = LogicalRouter(value)
                self.controller.router_updated(lrouter)
            elif action == 'delete':
                lrouter_id = key
                self.controller.router_deleted(lrouter_id)
        elif 'chassis' == table:
            if action == 'set' or action == 'create':
                chassis = Chassis(value)
                self.controller.chassis_created(chassis)
            elif action == 'delete':
                chassis_id = key
                self.controller.chassis_deleted(chassis_id)
        elif 'lswitch' == table:
            if action == 'set' or action == 'create':
                lswitch = LogicalSwitch(value)
                self.controller.logical_switch_updated(lswitch)
            elif action == 'delete':
                lswitch_id = key
                self.controller.logical_switch_deleted(lswitch_id)
        elif 'floatingip' == table:
            if action == 'set' or action == 'create':
                floatingip = Floatingip(value)
                self.controller.floatingip_updated(floatingip)
            elif action == 'delete':
                floatingip_id = key
                self.controller.floatingip_deleted(floatingip_id)
        elif pub_sub_api.PUBLISHER_TABLE == table:
            if action == 'set' or action == 'create':
                publisher = Publisher(value)
                self.controller.publisher_updated(publisher)
            elif action == 'delete':
                self.controller.publisher_deleted(key)
        elif 'ovsinterface' == table:
            if action == 'set' or action == 'create':
                ovs_port = OvsPort(value)
                self.controller.ovs_port_updated(ovs_port)
            elif action == 'sync_finished':
                self.controller.ovs_sync_finished()
            elif action == 'sync_started':
                self.controller.ovs_sync_started()
            elif action == 'delete':
                ovs_port = OvsPort(value)
                self.controller.ovs_port_deleted(ovs_port)
        elif 'log' == action:
            message = _LI(
                'Log event (Info): '
                'table: %(table)s '
                'key: %(key)s '
                'action: %(action)s '
                'value: %(value)s'
            )
            LOG.info(message, {
                'table': str(table),
                'key': str(key),
                'action': str(action),
                'value': str(value),
            })
        else:
            LOG.warning(_LW('Unknown table %s'), table)

    def sync(self):
        pass

    def create_security_group(self, id, topic, **columns):
        secgroup = {}
        secgroup['id'] = id
        secgroup['topic'] = topic
        for col, val in columns.items():
            secgroup[col] = val
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.create_key('secgroup', id, secgroup_json, topic)
        self._send_db_change_event('secgroup', id, 'create',
                                   secgroup_json, topic)

    def update_security_group(self, id, topic, **columns):
        secgroup_json = self.driver.get_key('secgroup', id, topic)
        secgroup = jsonutils.loads(secgroup_json)
        for col, val in columns.items():
            secgroup[col] = val
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.set_key('secgroup', id, secgroup_json, topic)
        self._send_db_change_event('secgroup', id, 'set',
                                   secgroup_json, topic)

    def delete_security_group(self, id, topic):
        self.driver.delete_key('secgroup', id, topic)
        self._send_db_change_event('secgroup', id, 'delete', id,
                                   topic)

    def add_security_group_rules(
            self, sg_id, topic, **columns):
        secgroup_json = self.driver.get_key('secgroup', sg_id, topic)
        new_rules = columns.get('sg_rules')
        sg_version_id = columns.get('sg_version')
        secgroup = jsonutils.loads(secgroup_json)
        rules = secgroup.get('rules', [])
        rules.extend(new_rules)
        secgroup['rules'] = rules
        secgroup['version'] = sg_version_id
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.set_key('secgroup', sg_id, secgroup_json,
                            secgroup['topic'])
        self._send_db_change_event('secgroup', sg_id, 'set', secgroup_json,
                                   secgroup['topic'])

    def delete_security_group_rule(
            self, sg_id, sgr_id, topic, **columns):
        secgroup_json = self.driver.get_key('secgroup', sg_id, topic)
        secgroup = jsonutils.loads(secgroup_json)
        sg_version_id = columns.get('sg_version')
        rules = secgroup.get('rules')
        new_rules = []
        for rule in rules:
            if rule['id'] != sgr_id:
                new_rules.append(rule)
        secgroup['rules'] = new_rules
        secgroup['version'] = sg_version_id
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.set_key('secgroup', sg_id, secgroup_json,
                            secgroup['topic'])
        self._send_db_change_event('secgroup', sg_id, 'set', secgroup_json,
                                   secgroup['topic'])

    def get_chassis(self, id):
        try:
            chassis_value = self.driver.get_key('chassis', id, None)
            return Chassis(chassis_value)
        except Exception:
            return None

    def get_all_chassis(self):
        res = []
        for entry_value in self.driver.get_all_entries('chassis', None):
            res.append(Chassis(entry_value))
        return res

    def add_chassis(self, id, ip, tunnel_type):
        chassis = {'id': id, 'ip': ip,
                   'tunnel_type': tunnel_type}
        chassis_json = jsonutils.dumps(chassis)
        self.driver.create_key('chassis', id, chassis_json, None)

    def get_lswitch(self, id, topic=None):
        try:
            lswitch_value = self.driver.get_key('lswitch', id, topic)
            return LogicalSwitch(lswitch_value)
        except Exception:
            return None

    def add_subnet(self, id, lswitch_id, topic, **columns):
        lswitch_json = self.driver.get_key('lswitch', lswitch_id, topic)
        lswitch = jsonutils.loads(lswitch_json)
        network_version = None

        subnet = {}
        subnet['id'] = id
        subnet['lswitch'] = lswitch_id
        subnet['topic'] = topic
        for col, val in columns.items():
            if col == 'nw_version':
                network_version = val
                continue
            subnet[col] = val

        subnets = lswitch.get('subnets', [])
        subnets.append(subnet)
        lswitch['subnets'] = subnets
        lswitch['version'] = network_version
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', lswitch_id, lswitch_json,
                            lswitch['topic'])
        self._send_db_change_event('lswitch', lswitch_id, 'set',
                                   lswitch_json, lswitch['topic'])

    def update_subnet(self, id, lswitch_id, topic, **columns):
        lswitch_json = self.driver.get_key('lswitch', lswitch_id, topic)
        lswitch = jsonutils.loads(lswitch_json)
        subnet = None
        network_version = None
        for s in lswitch.get('subnets', []):
            if s['id'] == id:
                subnet = s

        for col, val in columns.items():
            if col == 'nw_version':
                network_version = val
                continue
            subnet[col] = val

        lswitch['version'] = network_version

        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', lswitch_id, lswitch_json,
                            lswitch['topic'])
        self._send_db_change_event('lswitch', lswitch_id, 'set',
                                   lswitch_json, lswitch['topic'])

    def delete_subnet(self, id, lswitch_id, topic, **columns):
        lswitch_json = self.driver.get_key('lswitch', lswitch_id, topic)
        lswitch = jsonutils.loads(lswitch_json)
        network_version = columns.get('nw_version')

        new_ports = []
        for subnet in lswitch.get('subnets', []):
            if subnet['id'] != id:
                new_ports.append(subnet)

        lswitch['subnets'] = new_ports
        lswitch['version'] = network_version
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', lswitch_id, lswitch_json,
                            lswitch['topic'])
        self._send_db_change_event('lswitch', lswitch_id, 'set',
                                   lswitch_json, lswitch['topic'])

    def get_logical_port(self, port_id, topic=None):
        try:
            port_value = self.driver.get_key('lport', port_id, topic)
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

    def create_lswitch(self, id, topic, **columns):
        lswitch = {}
        lswitch['id'] = id
        lswitch['topic'] = topic
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.create_key('lswitch', id, lswitch_json, topic)
        self._send_db_change_event('lswitch', id, 'create', lswitch_json,
                                   topic)

    def update_lswitch(self, id, topic, **columns):
        lswitch_json = self.driver.get_key('lswitch', id, topic)
        lswitch = jsonutils.loads(lswitch_json)
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key('lswitch', id, lswitch_json, lswitch['topic'])
        self._send_db_change_event('lswitch', id, 'set', lswitch_json,
                                   lswitch['topic'])

    def delete_lswitch(self, id, topic):
        self.driver.delete_key('lswitch', id, topic)
        self._send_db_change_event('lswitch', id, 'delete', id, topic)

    def create_lport(self, id, lswitch_id, topic, **columns):
        lport = {}
        lport['id'] = id
        lport['lswitch'] = lswitch_id
        lport['topic'] = topic
        for col, val in columns.items():
            lport[col] = val
        lport_json = jsonutils.dumps(lport)
        self.driver.create_key('lport', id, lport_json, topic)
        self._send_db_change_event('lport', id, 'create', lport_json, topic)

    def update_lport(self, id, topic, **columns):
        lport_json = self.driver.get_key('lport', id, topic)
        lport = jsonutils.loads(lport_json)
        for col, val in columns.items():
            if val != const.ATTR_NOT_SPECIFIED:
                lport[col] = val
        lport_json = jsonutils.dumps(lport)
        self.driver.set_key('lport', id, lport_json, lport['topic'])
        self._send_db_change_event('lport', id, 'set', lport_json,
                                   lport['topic'])

    def delete_lport(self, id, topic):
        self.driver.delete_key('lport', id, topic)
        self._send_db_change_event('lport', id, 'delete', id, topic)

    def create_lrouter(self, id, topic, **columns):
        lrouter = {}
        lrouter['id'] = id
        lrouter['topic'] = topic
        for col, val in columns.items():
            lrouter[col] = val
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.create_key('lrouter', id, lrouter_json, topic)
        self._send_db_change_event('lrouter', id, 'create', lrouter_json,
                                   topic)

    def update_lrouter(self, id, topic, **columns):
        #TODO(gampel) move the router ports to a separate table
        lrouter_json = self.driver.get_key('lrouter', id, topic)
        lrouter = jsonutils.loads(lrouter_json)
        for col, val in columns.items():
            lrouter[col] = val

        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.set_key('lrouter', id, lrouter_json, topic)
        self._send_db_change_event('lrouter', id, 'set', lrouter_json,
                                   topic)

    def delete_lrouter(self, id, topic):
        self.driver.delete_key('lrouter', id, topic)
        self._send_db_change_event('lrouter', id, 'delete', id,
                                   topic)

    def add_lrouter_port(self, id, lrouter_id, lswitch_id,
                         topic, **columns):
        lrouter_json = self.driver.get_key('lrouter', lrouter_id, topic)
        lrouter = jsonutils.loads(lrouter_json)
        router_version = None

        lrouter_port = {}
        lrouter_port['id'] = id
        lrouter_port['lrouter'] = lrouter_id
        lrouter_port['lswitch'] = lswitch_id
        lrouter_port['topic'] = topic
        for col, val in columns.items():
            if col == 'router_version':
                router_version = val
                continue
            lrouter_port[col] = val

        router_ports = lrouter.get('ports', [])
        router_ports.append(lrouter_port)
        lrouter['ports'] = router_ports
        lrouter['version'] = router_version
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.set_key('lrouter', lrouter_id, lrouter_json,
                            lrouter['topic'])
        self._send_db_change_event('lrouter', lrouter_id, 'set',
                                   lrouter_json, lrouter['topic'])

    def delete_lrouter_port(self, router_port_id, lrouter_id, topic,
                            **columns):
        lrouter_json = self.driver.get_key('lrouter', lrouter_id, topic)
        lrouter = jsonutils.loads(lrouter_json)
        router_version = columns.get('router_version')

        new_ports = []
        for port in lrouter.get('ports', []):
            if port['id'] != router_port_id:
                new_ports.append(port)

        lrouter['ports'] = new_ports
        lrouter['version'] = router_version
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.set_key('lrouter', lrouter_id, lrouter_json,
                            lrouter['topic'])
        self._send_db_change_event('lrouter', lrouter_id, 'set',
                                   lrouter_json, lrouter['topic'])

    def get_router(self, router_id, topic=None):
        try:
            lrouter_value = self.driver.get_key('lrouter', router_id, topic)
            return LogicalRouter(lrouter_value)
        except Exception:
            return None

    def get_routers(self, topic=None):
        res = []
        for lrouter_value in self.driver.get_all_entries('lrouter', topic):
            res.append(LogicalRouter(lrouter_value))
        return res

    def get_security_group(self, sg_id, topic=None):
        try:
            secgroup_value = self.driver.get_key('secgroup', sg_id, topic)
            return SecurityGroup(secgroup_value)
        except Exception:
            return None

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

    def create_floatingip(self, id, topic, **columns):
        floatingip = {}
        floatingip['id'] = id
        floatingip['topic'] = topic
        for col, val in columns.items():
            floatingip[col] = val
        floatingip_json = jsonutils.dumps(floatingip)
        self.driver.create_key('floatingip', id, floatingip_json, topic)
        if floatingip.get('port_id', None) is not None:
            self._send_db_change_event('floatingip', id, 'create',
                                       floatingip_json, topic)

    def delete_floatingip(self, id, topic):
        floatingip = self.driver.get_key('floatingip', id, topic)
        fip_dict = jsonutils.loads(floatingip)
        if fip_dict.get('port_id', None) is not None:
            self._send_db_change_event('floatingip', id, 'delete',
                                       id, topic)
        self.driver.delete_key('floatingip', id, topic)

    def update_floatingip(self, id, topic, notify, **columns):
        floatingip_json = self.driver.get_key('floatingip', id, topic)
        floatingip = jsonutils.loads(floatingip_json)
        for col, val in columns.items():
            floatingip[col] = val
        floatingip_json = jsonutils.dumps(floatingip)
        self.driver.set_key('floatingip', id, floatingip_json,
                            floatingip['topic'])
        if notify:
            self._send_db_change_event('floatingip', id, 'set',
                                       floatingip_json, floatingip['topic'])

    def get_floatingip(self, id, topic=None):
        try:
            floatingip_value = self.driver.get_key('floatingip', id, topic)
            return Floatingip(floatingip_value)
        except Exception:
            return None

    def get_floatingips(self, topic=None):
        res = []
        for floatingip in self.driver.get_all_entries('floatingip', topic):
            res.append(Floatingip(floatingip))
        return res

    def get_floatingip_by_logical_port(self, port_id):
        for floatingip in self.get_floatingips():
            if port_id == floatingip['port_id']:
                return Floatingip(floatingip)
        return None

    def create_publisher(self, uuid, topic, **columns):
        publisher = {
            'id': uuid,
            'topic': topic
        }
        publisher.update(columns)
        publisher_json = jsonutils.dumps(publisher)
        self.driver.create_key(
            pub_sub_api.PUBLISHER_TABLE,
            uuid,
            publisher_json, topic
        )
        self._send_db_change_event(
            pub_sub_api.PUBLISHER_TABLE,
            uuid,
            'create',
            publisher_json,
            topic,
        )

    def delete_publisher(self, uuid, topic):
        self.driver.delete_key(pub_sub_api.PUBLISHER_TABLE, uuid, topic)
        self._send_db_change_event(
            pub_sub_api.PUBLISHER_TABLE,
            uuid,
            'delete',
            uuid,
            topic,
        )

    def get_publisher(self, uuid, topic=None):
        try:
            publisher_value = self.driver.get_key(
                pub_sub_api.PUBLISHER_TABLE,
                uuid,
                topic,
            )
            return Publisher(publisher_value)
        except Exception:
            LOG.exception(_LE('Could not get publisher %s'), uuid)
            return None

    def get_publishers(self, topic=None):
        publishers_values = self.driver.get_all_entries(
            pub_sub_api.PUBLISHER_TABLE,
            topic,
        )
        publishers = [Publisher(value) for value in publishers_values]
        timeout = cfg.CONF.df.publisher_timeout

        def _publisher_not_too_old(publisher):
            last_activity_timestamp = publisher.get_last_activity_timestamp()
            return (last_activity_timestamp >= time.time() - timeout)
        filter(_publisher_not_too_old, publishers)
        return publishers

    def update_publisher(self, uuid, topic, **columns):
        publisher_value = self.driver.get_key(
            pub_sub_api.PUBLISHER_TABLE,
            uuid,
            topic,
        )
        publisher = jsonutils.loads(publisher_value)
        publisher.update(columns)
        publisher_value = jsonutils.dumps(publisher)
        self.driver.set_key(
            pub_sub_api.PUBLISHER_TABLE,
            uuid,
            publisher_value,
            topic,
        )
        self._send_db_change_event(
            pub_sub_api.PUBLISHER_TABLE,
            uuid,
            'set',
            publisher_value,
            topic,
        )


@six.add_metaclass(abc.ABCMeta)
class DbStoreObject(object):

    @abc.abstractmethod
    def get_id(self):
        """Return the ID of this object."""

    @abc.abstractmethod
    def get_topic(self):
        """
        Return the topic, i.e. ID of the tenant to which this object belongs.
        """


class Chassis(DbStoreObject):

    def __init__(self, value):
        self.chassis = jsonutils.loads(value)

    def get_id(self):
        return self.chassis['id']

    def get_name(self):
        return self.chassis['name']

    def get_ip(self):
        return self.chassis['ip']

    def get_encap_type(self):
        return self.chassis['tunnel_type']

    def get_topic(self):
        return None

    def __str__(self):
        return self.chassis.__str__()


class LogicalSwitch(DbStoreObject):

    def __init__(self, value):
        self.lswitch = jsonutils.loads(value)

    def get_id(self):
        return self.lswitch['id']

    def get_name(self):
        return self.lswitch['name']

    def is_external(self):
        return self.lswitch.get('router_external', None)

    def get_mtu(self):
        return self.lswitch.get('mtu', None)

    def get_subnets(self):
        subnets = self.lswitch.get('subnets')
        if subnets:
            return [Subnet(subnet) for subnet in subnets]
        else:
            return []

    def get_topic(self):
        return self.lswitch['topic']

    def get_version(self):
        return self.lswitch['version']

    def get_segment_id(self):
        return self.lswitch.get('segmentation_id', None)

    def get_network_type(self):
        return self.lswitch.get('network_type', None)

    def __str__(self):
        return self.lswitch.__str__()

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.lswitch == other.lswitch
        else:
            return False


class Subnet(DbStoreObject):

    def __init__(self, value):
        self.subnet = value

    def enable_dhcp(self):
        return self.subnet['enable_dhcp']

    def get_id(self):
        return self.subnet['id']

    def get_name(self):
        return self.subnet['name']

    def get_dhcp_server_address(self):
        return self.subnet['dhcp_ip']

    def get_cidr(self):
        return self.subnet['cidr']

    def get_gateway_ip(self):
        return self.subnet['gateway_ip']

    def get_dns_name_servers(self):
        return self.subnet['dns_nameservers']

    def get_topic(self):
        return self.subnet['topic']

    def get_host_routes(self):
        return self.subnet.get('host_routes', [])


class LogicalPort(DbStoreObject):

    def __init__(self, value):
        self.external_dict = {}
        self.lport = jsonutils.loads(value)

    def get_id(self):
        return self.lport.get('id')

    def get_name(self):
        return self.lport.get('name')

    def get_ip(self):
        return self.lport['ips'][0]

    def get_ip_list(self):
        return self.lport['ips']

    def get_subnets(self):
        return self.lport['subnets']

    def get_mac(self):
        return self.lport['macs'][0]

    def get_chassis(self):
        return self.lport.get('chassis')

    def get_lswitch_id(self):
        return self.lport.get('lswitch')

    def get_tunnel_key(self):
        return int(self.lport['tunnel_key'])

    def get_security_groups(self):
        return self.lport.get('security_groups', [])

    def get_allow_address_pairs(self):
        return self.lport.get('allowed_address_pairs', [])

    def get_port_security_enable(self):
        return self.lport.get('port_security_enabled', False)

    def set_external_value(self, key, value):
        self.external_dict[key] = value

    def get_external_value(self, key):
        return self.external_dict.get(key)

    def get_device_owner(self):
        return self.lport.get('device_owner')

    def get_device_id(self):
        return self.lport.get('device_id')

    def get_topic(self):
        return self.lport.get('topic')

    def get_binding_profile(self):
        return self.lport.get('binding_profile')

    def get_binding_vnic_type(self):
        return self.lport.get('binding_vnic_type')

    def get_version(self):
        return self.lport['version']

    def get_remote_vtep(self):
        return self.lport.get('remote_vtep', False)

    def __str__(self):
        return self.lport.__str__() + self.external_dict.__str__()


class LogicalRouter(DbStoreObject):

    def __init__(self, value):
        self.lrouter = jsonutils.loads(value)

    def get_id(self):
        return self.lrouter.get('id')

    def get_name(self):
        return self.lrouter.get('name')

    def get_ports(self):
        ports = self.lrouter.get('ports')
        if ports:
            return [LogicalRouterPort(port) for port in ports]
        else:
            return []

    def get_topic(self):
        return self.lrouter.get('topic')

    def get_version(self):
        return self.lrouter['version']

    def get_routes(self):
        return self.lrouter.get('routes', [])

    def is_distributed(self):
        return self.lrouter.get('distributed', False)

    def get_external_gateway(self):
        return self.lrouter.get('gateway', {})

    def __str__(self):
        return self.lrouter.__str__()


class LogicalRouterPort(DbStoreObject):

    def __init__(self, value):
        self.router_port = value
        self.cidr = netaddr.IPNetwork(self.router_port['network'])

    def get_id(self):
        return self.router_port.get('id')

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

    def get_topic(self):
        return self.router_port['topic']

    def __eq__(self, other):
        return self.get_id() == other.get_id()

    def __str__(self):
        return self.router_port.__str__()


class SecurityGroup(DbStoreObject):

    def __init__(self, value):
        self.secgroup = jsonutils.loads(value)

    def get_id(self):
        return self.secgroup.get('id')

    def get_name(self):
        return self.secgroup.get('name')

    def get_topic(self):
        return self.secgroup.get('topic')

    def get_version(self):
        return self.secgroup.get('version')

    def get_rules(self):
        rules = self.secgroup.get('rules')
        if rules:
            return [SecurityGroupRule(rule) for rule in rules]
        else:
            return []

    def __str__(self):
        return self.secgroup.__str__()


class SecurityGroupRule(DbStoreObject):

    def __init__(self, value):
        self.secrule = value

    def get_id(self):
        return self.secrule.get('id')

    def get_topic(self):
        return self.secrule.get('topic')

    def get_direction(self):
        return self.secrule['direction']

    def get_ethertype(self):
        return self.secrule['ethertype']

    def get_port_range_max(self):
        return self.secrule['port_range_max']

    def get_port_range_min(self):
        return self.secrule['port_range_min']

    def get_protocol(self):
        return self.secrule['protocol']

    def get_remote_group_id(self):
        return self.secrule['remote_group_id']

    def get_remote_ip_prefix(self):
        return self.secrule['remote_ip_prefix']

    def get_security_group_id(self):
        return self.secrule['security_group_id']

    def __eq__(self, other):
        return self.get_id() == other.get_id()

    def __str__(self):
        return self.secrule.__str__()


class Floatingip(DbStoreObject):

    def __init__(self, value):
        self.floatingip = jsonutils.loads(value)

    def get_id(self):
        return self.floatingip['id']

    def get_version(self):
        return self.floatingip.get('version')

    def get_name(self):
        return self.floatingip['name']

    def get_status(self):
        return self.floatingip['status']

    def update_fip_status(self, status):
        self.floatingip['status'] = status

    def get_ip_address(self):
        return self.floatingip['floating_ip_address']

    def get_mac_address(self):
        return self.floatingip['floating_mac_address']

    def get_lport_id(self):
        return self.floatingip['port_id']

    def get_fixed_ip_address(self):
        return self.floatingip['fixed_ip_address']

    def get_lrouter_id(self):
        return self.floatingip['router_id']

    def get_topic(self):
        return self.floatingip['topic']

    def get_external_gateway_ip(self):
        return self.floatingip['external_gateway_ip']

    def set_external_gateway_ip(self, gw_ip):
        self.floatingip['external_gateway_ip'] = gw_ip

    def get_floating_network_id(self):
        return self.floatingip['floating_network_id']

    def get_external_cidr(self):
        return self.floatingip['external_cidr']

    def get_floating_port_id(self):
        return self.floatingip['floating_port_id']

    def __str__(self):
        return self.floatingip.__str__()


class OvsPort(DbStoreObject):

    TYPE_VM = 'vm'
    TYPE_TUNNEL = 'tunnel'
    TYPE_BRIDGE = 'bridge'
    TYPE_PATCH = 'patch'

    def __init__(self, value):
        self.ovs_port = value

    def get_id(self):
        return self.ovs_port.get_id()

    def get_topic(self):
        return None

    def get_ofport(self):
        return self.ovs_port.get_ofport()

    def get_name(self):
        return self.ovs_port.get_name()

    def get_admin_state(self):
        return self.ovs_port.get_admin_state()

    def get_type(self):
        return self.ovs_port.get_type()

    def get_iface_id(self):
        return self.ovs_port.get_iface_id()

    def get_peer(self):
        return self.ovs_port.get_peer()

    def get_attached_mac(self):
        return self.ovs_port.get_attached_mac()

    def get_mac_in_use(self):
        return self.ovs_port.get_mac_in_use()

    def get_remote_ip(self):
        return self.ovs_port.get_remote_ip()

    def get_tunnel_type(self):
        return self.ovs_port.get_tunnel_type()

    def __str__(self):
        return str(self.ovs_port)


class Publisher(DbStoreObject):

    def __init__(self, value):
        self.publisher = jsonutils.loads(value)

    def get_id(self):
        return self.publisher['id']

    def get_topic(self):
        return self.publisher.get('topic', None)

    def get_uri(self):
        return self.publisher.get('uri', None)

    def get_last_activity_timestamp(self):
        return self.publisher.get('last_activity_timestamp', None)

    def __str__(self):
        return str(self.publisher)
