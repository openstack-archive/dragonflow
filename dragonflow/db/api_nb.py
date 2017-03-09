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

import time

import eventlet
from jsonmodels import errors
from neutron_lib import constants as const
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import excutils

from dragonflow._i18n import _LI, _LW, _LE
import dragonflow.common.exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import model_framework as mf
from dragonflow.db import models as db_models

LOG = log.getLogger(__name__)


DB_ACTION_LIST = ['create', 'set', 'delete', 'log',
                  'sync', 'sync_started', 'sync_finished', 'dbrestart',
                  'db_sync']

_nb_api = None


def _get_topic(obj):
    try:
        return getattr(obj, 'topic', None)
    except errors.ValidationError:
        return None


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
        self.pub_sub_use_multiproc = False
        if self.is_neutron_server:
            # multiproc pub/sub is only supported in neutron server
            self.pub_sub_use_multiproc = cfg.CONF.df.pub_sub_use_multiproc

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
                self.publisher.initialize()
                # Start a thread to detect DB failover in Plugin
                self.publisher.set_publisher_for_failover(
                    self.publisher,
                    self.db_recover_callback)
                self.publisher.start_detect_for_failover()
                self.driver.set_neutron_server(True)
            else:
                # FIXME(nick-ma-z): if active-detection is enabled,
                # we initialize the publisher here. Make sure it
                # only supports redis-based pub/sub driver.
                if "ActivePortDetectionApp" in cfg.CONF.df.apps_list:
                    self.publisher.initialize()

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
            self.db_consistency_manager.process(direct=True)

    def _get_publisher(self):
        if self.pub_sub_use_multiproc:
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
        if not self.use_pubsub:
            return

        if not self.enable_selective_topo_dist or topic is None:
            topic = db_common.SEND_ALL_TOPIC
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        self.publisher.send_event(update)
        eventlet.sleep(0)

    def get_neutron_listener(self, id):
        try:
            listener = self.driver.get_key(db_models.Listener.table_name, id)
            return db_models.Listener(listener)
        except Exception:
            return None

    def get_all_neutron_listeners(self):
        listeners = self.driver.get_all_entries(db_models.Listener.table_name)
        return [db_models.Listener(l) for l in listeners]

    def create_neutron_listener(self, id, **columns):
        listener = {
            'id': id
        }
        listener.update(columns)
        listener_json = jsonutils.dumps(listener)
        self.driver.create_key(db_models.Listener.table_name, id,
                               listener_json)

    def update_neutron_listener(self, id, **columns):
        listener_json = self.driver.get_key(db_models.Listener.table_name, id)
        listener = jsonutils.loads(listener_json)
        listener.update(columns)
        listener_json = jsonutils.dumps(listener)
        self.driver.set_key(db_models.Listener.table_name, id, listener_json)

    def delete_neutron_listener(self, host):
        self.driver.delete_key(db_models.Listener.table_name, host)

    def register_notification_callback(self, controller):
        self.controller = controller
        LOG.info(_LI("DB configuration sync finished, waiting for changes"))
        if not self.use_pubsub:
            self.driver.register_notification_callback(
                self.db_change_callback)
        self._read_db_changes_from_queue()

    def register_listener_callback(self, cb, topic):
        """Register a callback for Neutron listener

        This method is used to register a callback for Neutron listener
        to handle the message from Dragonflow controller. It should only be
        called from Neutron side and only once.

        :param: a callback method to handle the message from Dragonflow
                controller
        :param topic: the topic this neutron listener cares about, e.g the
                      hostname of the node
        """
        if not self.use_pubsub:
            self.driver.register_notification_callback(cb)
            return
        self.subscriber.initialize(cb)
        self.subscriber.register_topic(topic)
        self.subscriber.daemonize()

    def db_change_callback(self, table, key, action, value, topic=None):
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        LOG.debug("Pushing Update to Queue: %s", update)
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
            self.controller.run_sync(value)
            return
        elif action == 'dbrestart':
            self.db_recover_callback()
            return
        elif action == 'db_sync':
            self.db_consistency_manager.process(direct=False)
            return

        try:
            model_class = mf.get_model(table)
        except KeyError:
            # Model class not found, possibly update was not about a model
            pass
        else:
            if action == 'delete':
                self.controller.delete_by_id(model_class, key)
            else:
                obj = model_class.from_json(value)
                self.controller.update(obj)
            return

        if 'ovsinterface' == table:
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
        if not df_utils.is_valid_version(lport, columns):
            return
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
        lrouter[db_models.UNIQUE_KEY] = self.driver.allocate_unique_key(
            db_models.LogicalRouter.table_name)
        for col, val in columns.items():
            lrouter[col] = val
        lrouter_json = jsonutils.dumps(lrouter)
        self.driver.create_key(db_models.LogicalRouter.table_name,
                               id, lrouter_json, topic)
        self._send_db_change_event(db_models.LogicalRouter.table_name,
                                   id, 'create', lrouter_json, topic)

    def update_lrouter(self, id, topic, **columns):
        # TODO(gampel) move the router ports to a separate table
        lrouter_json = self.driver.get_key(db_models.LogicalRouter.table_name,
                                           id, topic)
        lrouter = jsonutils.loads(lrouter_json)
        if not df_utils.is_valid_version(lrouter, columns):
            return
        lrouter.update(columns)
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
        router_version = columns.pop('router_version', None)
        router_dict = {'id': lrouter_id, 'version': router_version}
        if not df_utils.is_valid_version(lrouter, router_dict):
            return

        lrouter_port = {}
        lrouter_port['id'] = id
        lrouter_port['lrouter'] = lrouter_id
        lrouter_port['lswitch'] = lswitch_id
        lrouter_port['topic'] = topic
        for col, val in columns.items():
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
        router_version = columns.pop('router_version', None)
        router_dict = {'id': lrouter_id, 'version': router_version}
        if not df_utils.is_valid_version(lrouter, router_dict):
            return

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

    def create_floatingip(self, id, topic, **columns):
        floatingip = {}
        floatingip['id'] = id
        floatingip['topic'] = topic
        for col, val in columns.items():
            floatingip[col] = val
        floatingip_json = jsonutils.dumps(floatingip)
        self.driver.create_key(db_models.Floatingip.table_name,
                               id, floatingip_json, topic)
        if floatingip.get('port_id') is not None:
            self._send_db_change_event(db_models.Floatingip.table_name,
                                       id, 'create', floatingip_json, topic)

    def delete_floatingip(self, id, topic):
        floatingip = self.driver.get_key(db_models.Floatingip.table_name,
                                         id, topic)
        fip_dict = jsonutils.loads(floatingip)
        if fip_dict.get('port_id') is not None:
            self._send_db_change_event(db_models.Floatingip.table_name,
                                       id, 'delete', id, topic)
        self.driver.delete_key('floatingip', id, topic)

    def update_floatingip(self, id, topic, notify, **columns):
        floatingip_json = self.driver.get_key(db_models.Floatingip.table_name,
                                              id, topic)
        floatingip = jsonutils.loads(floatingip_json)
        if not df_utils.is_valid_version(floatingip, columns):
            return
        floatingip.update(columns)
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

    def create_active_port(self, id, topic, **columns):
        active_port = {'topic': topic}
        for col, val in columns.items():
            active_port[col] = val
        active_port_json = jsonutils.dumps(active_port)
        self.driver.create_key(
            db_models.AllowedAddressPairsActivePort.table_name, id,
            active_port_json, topic)
        self._send_db_change_event(
            db_models.AllowedAddressPairsActivePort.table_name, id, 'create',
            active_port_json, topic)

    def update_active_port(self, id, topic, **columns):
        active_port_json = self.driver.get_key(
            db_models.AllowedAddressPairsActivePort.table_name, id, topic)
        active_port = jsonutils.loads(active_port_json)
        active_port['topic'] = topic
        for col, val in columns.items():
            active_port[col] = val
        active_port_json = jsonutils.dumps(active_port)
        self.driver.set_key(db_models.AllowedAddressPairsActivePort.table_name,
                            id, active_port_json, topic)
        self._send_db_change_event(
            db_models.AllowedAddressPairsActivePort.table_name, id, 'set',
            active_port_json, topic)

    def delete_active_port(self, id, topic):
        self.driver.delete_key(
            db_models.AllowedAddressPairsActivePort.table_name, id, topic)
        self._send_db_change_event(
            db_models.AllowedAddressPairsActivePort.table_name, id, 'delete',
            id, topic)

    def get_active_ports(self, topic=None):
        res = []
        for active_port_json in self.driver.get_all_entries(
                db_models.AllowedAddressPairsActivePort.table_name, topic):
            res.append(db_models.AllowedAddressPairsActivePort(
                active_port_json))
        return res

    def create(self, obj):
        """Create the provided object in the database and publish an event
           about its creation.
        """
        model = type(obj)
        obj.on_create_pre()
        serialized_obj = obj.to_json()
        topic = _get_topic(obj)
        self.driver.create_key(model.table_name, obj.id,
                               serialized_obj, topic)
        self._send_db_change_event(model.table_name, obj.id, 'create',
                                   serialized_obj, topic)

    def update(self, obj):
        """Update the provided object in the database and publish an event
           about the change.

           This method reads the existing object from the database and updates
           any non-empty fields of the provided object. Retrieval happens by
           id/topic fields.
        """
        model = type(obj)
        full_obj = self.get(obj)

        if full_obj is None:
            raise df_exceptions.DBKeyNotFound(key=obj.id)

        changed_fields = full_obj.update(obj)

        if not changed_fields:
            return

        full_obj.on_update_pre()
        serialized_obj = full_obj.to_json()
        topic = _get_topic(full_obj)

        self.driver.set_key(model.table_name, full_obj.id,
                            serialized_obj, topic)
        self._send_db_change_event(model.table_name, full_obj.id, 'set',
                                   serialized_obj, topic)

    def delete(self, obj):
        """Delete the provided object from the database and publish the event
           about its deletion.

           The provided object does not have to have all the fields filled,
           just the ID / topic (if applicable) of the object we wish to delete.
        """
        model = type(obj)
        obj.on_delete_pre()
        topic = _get_topic(obj)
        try:
            self.driver.delete_key(model.table_name, obj.id, topic)
        except df_exceptions.DBKeyNotFound:
            with excutils.save_and_reraise_exception():
                LOG.warning(
                    _LW('Could not find object %(id)s to delete in %(table)s'),
                    extra={'id': id, 'table': model.table_name})

        self._send_db_change_event(model.table_name, obj.id, 'delete',
                                   obj.id, topic)

    def get(self, lean_obj):
        """Retrieve a model instance from the database. This function uses
           lean_obj to deduce ID and model type

           >>> nb_api.get(Chassis(id="one"))
           Chassis(id="One", ip="192.168.121.22", tunnel_types=["vxlan"])

        """
        model = type(lean_obj)
        try:
            serialized_obj = self.driver.get_key(
                model.table_name,
                lean_obj.id,
                _get_topic(lean_obj),
            )
        except df_exceptions.DBKeyNotFound:
            LOG.exception(
                _LE('Could not get object %(id)s from table %(table)s'),
                extra={'id': id, 'table': model.table_name})
        else:
            return model.from_json(serialized_obj)

    def get_all(self, model, topic=None):
        """Get all instances of provided model, can be limited to instances
           with a specific topic.
        """
        all_values = self.driver.get_all_entries(model.table_name, topic)
        all_objects = [model.from_json(e) for e in all_values]
        return model.on_get_all_post(all_objects)
