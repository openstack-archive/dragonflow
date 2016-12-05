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

import collections
import random
import time

import eventlet
from neutron_lib import constants as const
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
import six

from dragonflow._i18n import _LI, _LW, _LE
from dragonflow.common import exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import models as db_models

LOG = log.getLogger(__name__)


DB_ACTION_LIST = ['create', 'set', 'delete', 'log',
                  'sync', 'sync_started', 'sync_finished', 'dbrestart',
                  'db_sync']

_nb_api = None
PubSub = collections.namedtuple('PubSub', ('publisher', 'subscriber'))


class NbApi(object):

    def __init__(self, db_driver, use_pubsub=False, is_neutron_server=False):
        super(NbApi, self).__init__()
        self.driver = db_driver
        self.controller = None
        self._queue = eventlet.queue.PriorityQueue()
        self.use_pubsub = use_pubsub
        self.pubsub = None
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

        self.chassis = self._ChassisCRUDHelper(self, db_models.Chassis)
        self.lport = self._LportCRUDHelper(self, db_models.LogicalPort)
        self.lswitch = self._LswitchCRUDHelper(self, db_models.LogicalSwitch)
        self.lrouter = self._RouterCRUDHelper(self, db_models.LogicalRouter)
        self.security_group = self._SecurityGroupCRUDHelper(
            self,
            db_models.SecurityGroup,
        )
        self.floatingip = self._FloatingipCRUDHelper(
            self,
            db_models.Floatingip,
        )
        self.publisher = self._CRUDHelper(self, db_models.Publisher)
        self.qos_policy = self._CRUDHelper(self, db_models.QosPolicy)

        if self.use_pubsub:
            self.pubsub = PubSub(
                publisher=self._get_publisher(),
                subscriber=self._get_subscriber(),
            )
            if self.is_neutron_server:
                # Publisher is part of the neutron server Plugin
                self.pubsub.publisher.initialize()
                # Start a thread to detect DB failover in Plugin
                self.pubsub.publisher.set_publisher_for_failover(
                    self.pubsub.publisher,
                    self.db_recover_callback)
                self.pubsub.publisher.start_detect_for_failover()
                self.driver.set_neutron_server(True)
            else:
                # NOTE(gampel) we want to start queuing event as soon
                # as possible
                self._start_subscriber()
                # Register for DB Failover detection in NB Plugin
                self.pubsub.subscriber.set_subscriber_for_failover(
                    self.pubsub.subscriber,
                    self.db_change_callback)
                self.pubsub.subscriber.register_hamsg_for_db()

    def set_db_consistency_manager(self, db_consistency_manager):
        self.db_consistency_manager = db_consistency_manager

    def db_recover_callback(self):
        # only db with HA func can go in here
        self.driver.process_ha()
        self.pubsub.publisher.process_ha()
        self.pubsub.subscriber.process_ha()
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
        self.pubsub.subscriber.initialize(self.db_change_callback)
        self.pubsub.subscriber.register_topic(db_common.SEND_ALL_TOPIC)
        publishers_ips = cfg.CONF.df.publishers_ips
        uris = {'%s://%s:%s' % (
                cfg.CONF.df.publisher_transport,
                ip,
                cfg.CONF.df.publisher_port) for ip in publishers_ips}
        publishers = self.get_publishers()
        uris |= {publisher.get_uri() for publisher in publishers}
        for uri in uris:
            self.pubsub.subscriber.register_listen_address(uri)
        self.pubsub.subscriber.daemonize()

    def support_publish_subscribe(self):
        if self.use_pubsub:
            return True
        return self.driver.support_publish_subscribe()

    def _send_db_change_event(self, table, key, action, value, topic):
        if self.use_pubsub:
            if not self.enable_selective_topo_dist:
                topic = db_common.SEND_ALL_TOPIC
            update = db_common.DbUpdate(table, key, action, value, topic=topic)
            self.pubsub.publisher.send_event(update)
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

    def get_qos_policies(self, topic=None):
        res = []
        for qos in self.driver.get_all_entries(
                db_models.QosPolicy.table_name, topic):
            res.append(db_models.QosPolicy(qos))
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

    class _CRUDHelper(object):
        def __init__(self, api_nb, model):
            self.api_nb = api_nb
            self.model = model
            self.table_name = model.table_name

        @classmethod
        def _serialize_object(cls, id, topic, columns):
            obj = {
                'id': id,
                'topic': topic,
            }
            obj.update(columns)
            return jsonutils.dumps(obj)

        def create(self, id, topic, notify=True, **columns):
            obj_json = self._serialize_object(id, topic, columns)
            self.api_nb.driver.create_key(self.table_name, id, obj_json, topic)
            if notify:
                self.api_nb._send_db_change_event(self.table_name, id,
                                                  'create', obj_json, topic)

        def update(self, id, topic, notify=True, **columns):
            original = self._get_dict(id, topic)

            for key, value in six.iteritems(columns):
                if value != const.ATTR_NOT_SPECIFIED:
                    original[key] = value

            self._set_object(id, topic, original, notify)

        def _set_object(self, id, topic, obj, notify=True):
            obj_json = self._serialize_object(id, topic, obj)
            self.api_nb.driver.set_key(self.table_name, id, obj_json, topic)
            if notify:
                self.api_nb._send_db_change_event(self.table_name, id, 'set',
                                                  obj_json, topic)

        def delete(self, id, topic=None):
            try:
                self.api_nb.driver.delete_key(self.table_name, id, topic)
                self.api_nb._send_db_change_event(self.table_name, id,
                                                  'delete', id, topic)
            except df_exceptions.DBKeyNotFound:
                LOG.warning(
                    _LW('Could not find object %(id)s to delete in %(table)s'),
                    extra={'id': id, 'table': self.table_name})
                raise

        def _get_raw(self, id, topic=None):
            return self.api_nb.driver.get_key(self.table_name, id, topic)

        def get(self, id, topic=None):
            try:
                value = self._get_raw(id, topic)
                return self.model(value)
            except Exception:
                LOG.exception(
                    _LE('Could not get object %(id)s from table %(table)s'),
                    extra={'id': id, 'table': self.table_name})
                return None

        def _get_dict(self, id, topic=None):
            return jsonutils.loads(self._get_raw(id, topic))

        def get_all(self, topic=None):
            res = self.api_nb.driver.get_all_entries(self.table_name, topic)
            return [self.model(v) for v in res]

        def _add_element(self, id, topic, new_version, elem_name, nested_obj):
            obj = self._get_dict(id, topic)
            obj['version'] = new_version
            obj.setdefault(elem_name, []).append(nested_obj)
            self._set_object(id, topic, obj)

        def _update_element(self, id, topic, new_version, elem_name,
                            elem_id, update_dict):
            obj = self._get_dict(id, topic)
            obj['version'] = new_version
            for elem in obj.setdefault(elem_name, []):
                if elem['id'] == elem_id:
                    elem.update(update_dict)
                    break
            self._set_object(id, topic, obj)

        def _remove_element(self, id, topic, new_version,
                            elem_name, nested_id):
            obj = self._get_dict(id, topic)
            obj['version'] = new_version
            obj[elem_name] = [
                e for e in obj.setdefault(elem_name, [])
                if e['id'] != nested_id
            ]
            self._set_object(id, topic, obj)

    class _UniqueKeyCRUDHelper(_CRUDHelper):
        def create(self, id, topic, notify=True, **columns):
            unique_key = self.api_nb.driver.allocate_unique_key(
                self.table_name)
            columns[db_models.UNIQUE_KEY] = unique_key
            return super(NbApi._UniqueKeyCRUDHelper, self).create(
                id, topic, notify, **columns)

    class _RouterCRUDHelper(_CRUDHelper):
        def add_port(self, id, topic, version, port_id, lswitch_id, **columns):
            port = {
                'id': port_id,
                'lrouter': id,
                'lswitch': lswitch_id,
                'topic': topic,
            }
            port.update(columns)
            self._add_element(id, topic, version, 'ports', port)

        def delete_port(self, id, topic, port_id, version):
            self._remove_element(id, topic, version, 'ports', port_id)

    class _SecurityGroupCRUDHelper(_UniqueKeyCRUDHelper):
        def add_rule(self, id, topic, version, rule):
            self._add_element(id, topic, version, 'rules', rule)

        def delete_rule(self, id, topic, version, rule_id):
            self._remove_element(id, topic, version, 'rules', rule_id)

    class _LswitchCRUDHelper(_UniqueKeyCRUDHelper):
        def add_subnet(self, id, topic, version, subnet_id, **columns):
            subnet = {
                'id': subnet_id,
                'lswitch': id,
                'topic': topic,
            }
            subnet.update(columns)
            self._add_element(id, topic, version, 'subnets', subnet)

        def delete_subnet(self, id, topic, version, subnet_id):
            self._remove_element(id, topic, version, 'subnets', subnet_id)

        def update_subnet(self, id, topic, version, subnet_id, **columns):
            self._update_element(id, topic, version, 'subnets',
                                 subnet_id, columns)

    class _ChassisCRUDHelper(_CRUDHelper):
        def create(self, id, ip, tunnel_type):
            obj_json = jsonutils.dumps({
                'id': id,
                'ip': ip,
                'tunnel_type': tunnel_type,
            })
            self.api_nb.driver.create_key(self.table_name, id, obj_json)
            self.api_nb._send_db_change_event(self.table_name, id,
                                              'create', obj_json)

    class _LportCRUDHelper(_UniqueKeyCRUDHelper):
        def get_all(self, topic=None):
            ports = super(NbApi._LportCRUDHelper, self).get_all(topic)
            return [p for p in ports if p.get_chassis() is not None]

    class _FloatingipCRUDHelper(_CRUDHelper):
        def create(self, id, topic, notify=False, **columns):
            notify = notify or columns.get('port_id') is not None
            super(NbApi._FloatingipCRUDHelper, self).create(
                id, topic, notify=notify, **columns)
