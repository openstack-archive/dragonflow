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

import random
import time

import eventlet
from neutron_lib import constants as const
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils

from dragonflow._i18n import _LI, _LW, _LE
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import models as db_models

LOG = log.getLogger(__name__)


DB_ACTION_LIST = ['create', 'set', 'delete', 'log',
                  'sync', 'sync_started', 'sync_finished', 'dbrestart',
                  'db_sync']

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
        self.db_consistency_manager = None
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
                self.driver.set_neutron_server(True)
            else:
                # NOTE(gampel) we want to start queuing event as soon
                # as possible
                self._start_subscriber()
                # Register for DB Failover detection in NB Plugin
                self.subscriber.set_subscriber_for_failover(
                    self.subscriber,
                    self.db_change_callback)
                self.subscriber.register_hamsg_for_db()

    def set_db_consistency_manager(self, db_consistency_manager):
        self.db_consistency_manager = db_consistency_manager

    def db_recover_callback(self):
        # only db with HA func can go in here
        self.driver.process_ha()
        self.publisher.process_ha()
        self.subscriber.process_ha()
        if self.db_consistency_manager and not self.is_neutron_server:
            self.db_consistency_manager.process(True)

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

    def _start_subscriber(self):
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

    def get_all_port_status_keys(self):
        topics = self.driver.get_all_entries('portstats')
        topic = random.choice(topics)
        return topic

    def create_port_status(self, server_ip):
        self.driver.create_key('portstats', server_ip,
                               server_ip, None)

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
        elif action == 'db_sync':
            self.db_consistency_manager.process(False)
            return

        if db_models.QosPolicy.table_name == table:
            if action == 'set' or action == 'create':
                qos = db_models.QosPolicy(value)
                self.controller.qos_policy_updated(qos)
            elif action == 'delete':
                qos_id = key
                self.controller.qos_policy_deleted(qos_id)
        elif db_models.SecurityGroup.table_name == table:
            if action == 'set' or action == 'create':
                secgroup = db_models.SecurityGroup(value)
                self.controller.security_group_updated(secgroup)
            elif action == 'delete':
                secgroup_id = key
                self.controller.security_group_deleted(secgroup_id)
        elif db_models.LogicalPort.table_name == table:
            if action == 'set' or action == 'create':
                lport = db_models.LogicalPort(value)
                self.controller.logical_port_updated(lport)
            elif action == 'delete':
                lport_id = key
                self.controller.logical_port_deleted(lport_id)
        elif db_models.LogicalRouter.table_name == table:
            if action == 'set' or action == 'create':
                lrouter = db_models.LogicalRouter(value)
                self.controller.router_updated(lrouter)
            elif action == 'delete':
                lrouter_id = key
                self.controller.router_deleted(lrouter_id)
        elif db_models.Chassis.table_name == table:
            if action == 'set' or action == 'create':
                chassis = db_models.Chassis(value)
                self.controller.chassis_updated(chassis)
            elif action == 'delete':
                chassis_id = key
                self.controller.chassis_deleted(chassis_id)
        elif db_models.LogicalSwitch.table_name == table:
            if action == 'set' or action == 'create':
                lswitch = db_models.LogicalSwitch(value)
                self.controller.logical_switch_updated(lswitch)
            elif action == 'delete':
                lswitch_id = key
                self.controller.logical_switch_deleted(lswitch_id)
        elif db_models.Floatingip.table_name == table:
            if action == 'set' or action == 'create':
                floatingip = db_models.Floatingip(value)
                self.controller.floatingip_updated(floatingip)
            elif action == 'delete':
                floatingip_id = key
                self.controller.floatingip_deleted(floatingip_id)
        elif db_models.Publisher.table_name == table:
            if action == 'set' or action == 'create':
                publisher = db_models.Publisher(value)
                self.controller.publisher_updated(publisher)
            elif action == 'delete':
                self.controller.publisher_deleted(key)
        elif 'ovsinterface' == table:
            if action == 'set' or action == 'create':
                ovs_port = db_models.OvsPort(value)
                self.controller.ovs_port_updated(ovs_port)
            elif action == 'sync_finished':
                self.controller.ovs_sync_finished()
            elif action == 'sync_started':
                self.controller.ovs_sync_started()
            elif action == 'delete':
                ovs_port = db_models.OvsPort(value)
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

    def create_security_group(self, id, topic, **columns):
        secgroup = {}
        secgroup['id'] = id
        secgroup['topic'] = topic
        for col, val in columns.items():
            secgroup[col] = val
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.create_key(db_models.SecurityGroup.table_name,
                               id, secgroup_json, topic)
        self._send_db_change_event(db_models.SecurityGroup.table_name,
                                   id, 'create', secgroup_json, topic)

    def update_security_group(self, id, topic, **columns):
        secgroup_json = self.driver.get_key(db_models.SecurityGroup.table_name,
                                            id, topic)
        secgroup = jsonutils.loads(secgroup_json)
        for col, val in columns.items():
            secgroup[col] = val
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.set_key(db_models.SecurityGroup.table_name,
                            id, secgroup_json, topic)
        self._send_db_change_event(db_models.SecurityGroup.table_name,
                                   id, 'set', secgroup_json, topic)

    def delete_security_group(self, id, topic):
        self.driver.delete_key(db_models.SecurityGroup.table_name, id, topic)
        self._send_db_change_event(db_models.SecurityGroup.table_name,
                                   id, 'delete', id, topic)

    def add_security_group_rules(self, sg_id, topic, **columns):
        secgroup_json = self.driver.get_key(db_models.SecurityGroup.table_name,
                                            sg_id, topic)
        new_rules = columns.get('sg_rules')
        sg_version_id = columns.get('sg_version')
        secgroup = jsonutils.loads(secgroup_json)
        rules = secgroup.get('rules', [])
        rules.extend(new_rules)
        secgroup['rules'] = rules
        secgroup['version'] = sg_version_id
        secgroup_json = jsonutils.dumps(secgroup)
        self.driver.set_key(db_models.SecurityGroup.table_name,
                            sg_id, secgroup_json, secgroup['topic'])
        self._send_db_change_event(db_models.SecurityGroup.table_name,
                                   sg_id, 'set', secgroup_json,
                                   secgroup['topic'])

    def delete_security_group_rule(self, sg_id, sgr_id, topic, **columns):
        secgroup_json = self.driver.get_key(db_models.SecurityGroup.table_name,
                                            sg_id, topic)
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
        self.driver.set_key(db_models.SecurityGroup.table_name,
                            sg_id, secgroup_json,
                            secgroup['topic'])
        self._send_db_change_event(db_models.SecurityGroup.table_name,
                                   sg_id, 'set', secgroup_json,
                                   secgroup['topic'])

    def get_chassis(self, id):
        try:
            chassis_value = self.driver.get_key(db_models.Chassis.table_name,
                                                id, None)
            return db_models.Chassis(chassis_value)
        except Exception:
            return None

    def get_all_chassis(self):
        res = []
        for entry_value in self.driver.get_all_entries(
                db_models.Chassis.table_name, None):
            res.append(db_models.Chassis(entry_value))
        return res

    def add_chassis(self, id, ip, tunnel_type):
        chassis = {'id': id, 'ip': ip,
                   'tunnel_type': tunnel_type}
        chassis_json = jsonutils.dumps(chassis)
        self.driver.create_key(db_models.Chassis.table_name,
                               id, chassis_json, None)

    def update_chassis(self, id, **columns):
        chassis_json = self.driver.get_key('chassis', id)
        chassis = jsonutils.loads(chassis_json)
        for col, val in columns.items():
            chassis[col] = val

        chassis_json = jsonutils.dumps(chassis)
        self.driver.set_key('chassis', id, chassis_json, None)

    def get_lswitch(self, id, topic=None):
        try:
            lswitch_value = self.driver.get_key(
                db_models.LogicalSwitch.table_name, id, topic)
            return db_models.LogicalSwitch(lswitch_value)
        except Exception:
            return None

    def add_subnet(self, id, lswitch_id, topic, **columns):
        lswitch_json = self.driver.get_key(db_models.LogicalSwitch.table_name,
                                           lswitch_id, topic)
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
        self.driver.set_key(db_models.LogicalSwitch.table_name,
                            lswitch_id, lswitch_json, lswitch['topic'])
        self._send_db_change_event(db_models.LogicalSwitch.table_name,
                                   lswitch_id, 'set',
                                   lswitch_json, lswitch['topic'])

    def update_subnet(self, id, lswitch_id, topic, **columns):
        lswitch_json = self.driver.get_key(db_models.LogicalSwitch.table_name,
                                           lswitch_id, topic)
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
        self.driver.set_key(db_models.LogicalSwitch.table_name,
                            lswitch_id, lswitch_json, lswitch['topic'])
        self._send_db_change_event(db_models.LogicalSwitch.table_name,
                                   lswitch_id, 'set',
                                   lswitch_json, lswitch['topic'])

    def delete_subnet(self, id, lswitch_id, topic, **columns):
        lswitch_json = self.driver.get_key(db_models.LogicalSwitch.table_name,
                                           lswitch_id, topic)
        lswitch = jsonutils.loads(lswitch_json)
        network_version = columns.get('nw_version')

        new_ports = []
        for subnet in lswitch.get('subnets', []):
            if subnet['id'] != id:
                new_ports.append(subnet)

        lswitch['subnets'] = new_ports
        lswitch['version'] = network_version
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key(db_models.LogicalSwitch.table_name,
                            lswitch_id, lswitch_json,
                            lswitch['topic'])
        self._send_db_change_event(db_models.LogicalSwitch.table_name,
                                   lswitch_id, 'set',
                                   lswitch_json, lswitch['topic'])

    def get_logical_port(self, port_id, topic=None):
        try:
            port_value = self.driver.get_key(db_models.LogicalPort.table_name,
                                             port_id, topic)
            return db_models.LogicalPort(port_value)
        except Exception:
            return None

    def get_all_logical_ports(self, topic=None):
        res = []
        for lport_value in self.driver.get_all_entries(
                db_models.LogicalPort.table_name, topic):
            lport = db_models.LogicalPort(lport_value)
            if lport.get_chassis() is None:
                continue
            res.append(lport)
        return res

    def create_lswitch(self, id, topic, **columns):
        lswitch = {}
        lswitch['id'] = id
        lswitch['topic'] = topic
        lswitch[db_models.UNIQUE_KEY] = self.driver.allocate_unique_key(
            db_models.LogicalSwitch.table_name)
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.create_key(db_models.LogicalSwitch.table_name,
                               id, lswitch_json, topic)
        self._send_db_change_event(db_models.LogicalSwitch.table_name,
                                   id, 'create', lswitch_json, topic)

    def update_lswitch(self, id, topic, **columns):
        lswitch_json = self.driver.get_key(db_models.LogicalSwitch.table_name,
                                           id, topic)
        lswitch = jsonutils.loads(lswitch_json)
        for col, val in columns.items():
            lswitch[col] = val
        lswitch_json = jsonutils.dumps(lswitch)
        self.driver.set_key(db_models.LogicalSwitch.table_name,
                            id, lswitch_json, lswitch['topic'])
        self._send_db_change_event(db_models.LogicalSwitch.table_name,
                                   id, 'set', lswitch_json, lswitch['topic'])

    def delete_lswitch(self, id, topic):
        self.driver.delete_key(db_models.LogicalSwitch.table_name, id, topic)
        self._send_db_change_event(db_models.LogicalSwitch.table_name,
                                   id, 'delete', id, topic)

    def create_lport(self, id, lswitch_id, topic, **columns):
        lport = {}
        lport['id'] = id
        lport['lswitch'] = lswitch_id
        lport['topic'] = topic
        lport[db_models.UNIQUE_KEY] = self.driver.allocate_unique_key(
            db_models.LogicalPort.table_name)
        for col, val in columns.items():
            lport[col] = val
        lport_json = jsonutils.dumps(lport)
        self.driver.create_key(db_models.LogicalPort.table_name,
                               id, lport_json, topic)
        self._send_db_change_event(db_models.LogicalPort.table_name,
                                   id, 'create', lport_json, topic)

    def update_lport(self, id, topic, **columns):
        lport_json = self.driver.get_key(db_models.LogicalPort.table_name,
                                         id, topic)
        lport = jsonutils.loads(lport_json)
        for col, val in columns.items():
            if val != const.ATTR_NOT_SPECIFIED:
                lport[col] = val
        lport_json = jsonutils.dumps(lport)
        self.driver.set_key(db_models.LogicalPort.table_name,
                            id, lport_json, lport['topic'])
        self._send_db_change_event(db_models.LogicalPort.table_name,
                                   id, 'set', lport_json, lport['topic'])

    def delete_lport(self, id, topic):
        self.driver.delete_key(db_models.LogicalPort.table_name, id, topic)
        self._send_db_change_event(db_models.LogicalPort.table_name,
                                   id, 'delete', id, topic)

    def create_lrouter(self, id, topic, **columns):
        lrouter = {}
        lrouter['id'] = id
        lrouter['topic'] = topic
        for col, val in columns.items():
            lrouter[col] = val
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.create_key(db_models.LogicalRouter.table_name,
                               id, lrouter_json, topic)
        self._send_db_change_event(db_models.LogicalRouter.table_name,
                                   id, 'create', lrouter_json, topic)

    def update_lrouter(self, id, topic, **columns):
        #TODO(gampel) move the router ports to a separate table
        lrouter_json = self.driver.get_key(db_models.LogicalRouter.table_name,
                                           id, topic)
        lrouter = jsonutils.loads(lrouter_json)
        for col, val in columns.items():
            lrouter[col] = val

        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.set_key(db_models.LogicalRouter.table_name,
                            id, lrouter_json, topic)
        self._send_db_change_event(db_models.LogicalRouter.table_name,
                                   id, 'set', lrouter_json, topic)

    def delete_lrouter(self, id, topic):
        self.driver.delete_key(db_models.LogicalRouter.table_name, id, topic)
        self._send_db_change_event(db_models.LogicalRouter.table_name,
                                   id, 'delete', id, topic)

    def add_lrouter_port(self, id, lrouter_id, lswitch_id,
                         topic, **columns):
        lrouter_json = self.driver.get_key(db_models.LogicalRouter.table_name,
                                           lrouter_id, topic)
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
        self.driver.set_key(db_models.LogicalRouter.table_name,
                            lrouter_id, lrouter_json, lrouter['topic'])
        self._send_db_change_event(db_models.LogicalRouter.table_name,
                                   lrouter_id, 'set',
                                   lrouter_json, lrouter['topic'])

    def delete_lrouter_port(self, router_port_id, lrouter_id, topic,
                            **columns):
        lrouter_json = self.driver.get_key(db_models.LogicalRouter.table_name,
                                           lrouter_id, topic)
        lrouter = jsonutils.loads(lrouter_json)
        router_version = columns.get('router_version')

        new_ports = []
        for port in lrouter.get('ports', []):
            if port['id'] != router_port_id:
                new_ports.append(port)

        lrouter['ports'] = new_ports
        lrouter['version'] = router_version
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.set_key(db_models.LogicalRouter.table_name,
                            lrouter_id, lrouter_json, lrouter['topic'])
        self._send_db_change_event(db_models.LogicalRouter.table_name,
                                   lrouter_id, 'set',
                                   lrouter_json, lrouter['topic'])

    def get_router(self, router_id, topic=None):
        try:
            lrouter_value = self.driver.get_key(
                db_models.LogicalRouter.table_name, router_id, topic)
            return db_models.LogicalRouter(lrouter_value)
        except Exception:
            return None

    def get_routers(self, topic=None):
        res = []
        for lrouter_value in self.driver.get_all_entries(
                db_models.LogicalRouter.table_name, topic):
            res.append(db_models.LogicalRouter(lrouter_value))
        return res

    def get_security_group(self, sg_id, topic=None):
        try:
            secgroup_value = self.driver.get_key(
                db_models.SecurityGroup.table_name, sg_id, topic)
            return db_models.SecurityGroup(secgroup_value)
        except Exception:
            return None

    def get_security_groups(self, topic=None):
        res = []
        for secgroup_value in self.driver.get_all_entries(
                db_models.SecurityGroup.table_name, topic):
            res.append(db_models.SecurityGroup(secgroup_value))
        return res

    def get_qos_policies(self, topic=None):
        res = []
        for qos in self.driver.get_all_entries(
                db_models.QosPolicy.table_name, topic):
            res.append(db_models.QosPolicy(qos))
        return res

    def get_all_logical_switches(self, topic=None):
        res = []
        for lswitch_value in self.driver.get_all_entries(
                db_models.LogicalSwitch.table_name, topic):
            res.append(db_models.LogicalSwitch(lswitch_value))
        return res

    def create_floatingip(self, id, topic, **columns):
        floatingip = {}
        floatingip['id'] = id
        floatingip['topic'] = topic
        for col, val in columns.items():
            floatingip[col] = val
        floatingip_json = jsonutils.dumps(floatingip)
        self.driver.create_key(db_models.Floatingip.table_name,
                               id, floatingip_json, topic)
        if floatingip.get('port_id', None) is not None:
            self._send_db_change_event(db_models.Floatingip.table_name,
                                       id, 'create', floatingip_json, topic)

    def delete_floatingip(self, id, topic):
        floatingip = self.driver.get_key(db_models.Floatingip.table_name,
                                         id, topic)
        fip_dict = jsonutils.loads(floatingip)
        if fip_dict.get('port_id', None) is not None:
            self._send_db_change_event(db_models.Floatingip.table_name,
                                       id, 'delete', id, topic)
        self.driver.delete_key('floatingip', id, topic)

    def update_floatingip(self, id, topic, notify, **columns):
        floatingip_json = self.driver.get_key(db_models.Floatingip.table_name,
                                              id, topic)
        floatingip = jsonutils.loads(floatingip_json)
        for col, val in columns.items():
            floatingip[col] = val
        floatingip_json = jsonutils.dumps(floatingip)
        self.driver.set_key(db_models.Floatingip.table_name,
                            id, floatingip_json, floatingip['topic'])
        if notify:
            self._send_db_change_event(db_models.Floatingip.table_name,
                                       id, 'set',
                                       floatingip_json, floatingip['topic'])

    def get_floatingip(self, id, topic=None):
        try:
            floatingip_value = self.driver.get_key(
                db_models.Floatingip.table_name, id, topic)
            return db_models.Floatingip(floatingip_value)
        except Exception:
            return None

    def get_floatingips(self, topic=None):
        res = []
        for floatingip in self.driver.get_all_entries(
                db_models.Floatingip.table_name, topic):
            res.append(db_models.Floatingip(floatingip))
        return res

    def create_publisher(self, uuid, topic, **columns):
        publisher = {
            'id': uuid,
            'topic': topic
        }
        publisher.update(columns)
        publisher_json = jsonutils.dumps(publisher)
        self.driver.create_key(
            db_models.Publisher.table_name,
            uuid,
            publisher_json, topic
        )
        self._send_db_change_event(
            db_models.Publisher.table_name,
            uuid,
            'create',
            publisher_json,
            topic,
        )

    def delete_publisher(self, uuid, topic):
        self.driver.delete_key(db_models.Publisher.table_name, uuid, topic)
        self._send_db_change_event(
            db_models.Publisher.table_name,
            uuid,
            'delete',
            uuid,
            topic,
        )

    def get_publisher(self, uuid, topic=None):
        try:
            publisher_value = self.driver.get_key(
                db_models.Publisher.table_name,
                uuid,
                topic,
            )
            return db_models.Publisher(publisher_value)
        except Exception:
            LOG.exception(_LE('Could not get publisher %s'), uuid)
            return None

    def get_publishers(self, topic=None):
        publishers_values = self.driver.get_all_entries(
            db_models.Publisher.table_name,
            topic,
        )
        publishers = [db_models.Publisher(value)
                      for value in publishers_values]
        timeout = cfg.CONF.df.publisher_timeout

        def _publisher_not_too_old(publisher):
            last_activity_timestamp = publisher.get_last_activity_timestamp()
            return (last_activity_timestamp >= time.time() - timeout)
        filter(_publisher_not_too_old, publishers)
        return publishers

    def update_publisher(self, uuid, topic, **columns):
        publisher_value = self.driver.get_key(
            db_models.Publisher.table_name,
            uuid,
            topic,
        )
        publisher = jsonutils.loads(publisher_value)
        publisher.update(columns)
        publisher_value = jsonutils.dumps(publisher)
        self.driver.set_key(
            db_models.Publisher.table_name,
            uuid,
            publisher_value,
            topic,
        )
        self._send_db_change_event(
            db_models.Publisher.table_name,
            uuid,
            'set',
            publisher_value,
            topic,
        )

    def create_qos_policy(self, policy_id, topic, **columns):
        policy = {'id': policy_id,
                  'topic': topic}
        policy.update(columns)
        policy_json = jsonutils.dumps(policy)

        self.driver.create_key(db_models.QosPolicy.table_name,
                               policy_id, policy_json, topic)
        self._send_db_change_event(db_models.QosPolicy.table_name,
                                   policy_id, 'create',
                                   policy_json, topic)

    def update_qos_policy(self, policy_id, topic, **columns):
        qospolicy_json = self.driver.get_key(db_models.QosPolicy.table_name,
                                             policy_id, topic)
        policy = jsonutils.loads(qospolicy_json)
        policy.update(columns)
        policy_json = jsonutils.dumps(policy)

        self.driver.set_key(db_models.QosPolicy.table_name,
                            policy_id, policy_json, topic)
        self._send_db_change_event(db_models.QosPolicy.table_name,
                                   policy_id, 'set',
                                   policy_json, topic)

    def delete_qos_policy(self, policy_id, topic):
        self.driver.delete_key(db_models.QosPolicy.table_name,
                               policy_id, topic)
        self._send_db_change_event(db_models.QosPolicy.table_name,
                                   policy_id, 'delete', policy_id, topic)

    def get_qos_policy(self, policy_id, topic=None):
        try:
            qospolicy_value = self.driver.get_key(
                db_models.QosPolicy.table_name, policy_id, topic)
            return db_models.QosPolicy(qospolicy_value)
        except Exception:
            LOG.exception(_LE('Could not get qos policy %s'), policy_id)
            return None
