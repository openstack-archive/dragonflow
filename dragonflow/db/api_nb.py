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
from jsonmodels import errors
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import excutils

import dragonflow.common.exceptions as df_exceptions
from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import model_framework as mf
from dragonflow.db import model_proxy as mproxy
from dragonflow.db import models as db_models
from dragonflow.db.models import core


LOG = log.getLogger(__name__)


DB_ACTION_LIST = ['create', 'set', 'delete', 'log',
                  'sync', 'sync_started', 'sync_finished', 'dbrestart',
                  'db_sync', 'migrate']

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
        publishers = self.get_all(core.Publisher)
        uris |= {publisher.uri for publisher in publishers}
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

    def register_notification_callback(self, controller):
        self.controller = controller
        LOG.info("DB configuration sync finished, waiting for changes")
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
            LOG.warning('Unknown action %(action)s for table '
                        '%(table)s', {'action': action, 'table': table})
            return

        if action == 'sync':
            self.controller.run_sync(value)
        elif action == 'dbrestart':
            self.db_recover_callback()
        elif action == 'db_sync':
            self.db_consistency_manager.process(direct=False)
        elif action == 'ovs_sync_finished':
            self.controller.ovs_sync_finished()
        elif action == 'ovs_sync_started':
            self.controller.ovs_sync_started()
        elif 'log' == action:
            message = ('Log event (Info): table: %(table)s key: %(key)s '
                       'action: %(action)s value: %(value)s')

            LOG.info(message, {
                'table': str(table),
                'key': str(key),
                'action': str(action),
                'value': str(value),
            })
        elif table == 'lport_migration' and action == 'migrate':
            lport = db_models.LogicalPort(value)
            self.controller.update_migration_flows(lport)
        elif table is not None:
            try:
                model_class = mf.get_model(table)
            except KeyError:
                # Model class not found, possibly update was not about a model
                # Added lport migration for VM migration flag
                LOG.warning('Unknown table %s', table)
            else:
                if action == 'delete':
                    self.controller.delete_by_id(model_class, key)
                else:
                    obj = model_class.from_json(value)
                    self.controller.update(obj)

    # lport process for VM migration
    def set_lport_migration(self, port_id, chassis):
        port_migration = {'migration': chassis}
        migration_json = jsonutils.dumps(port_migration)
        self.driver.create_key('lport_migration', port_id, migration_json)

    def get_lport_migration(self, port_id):
        try:
            migration_json = self.driver.get_key('lport_migration', port_id)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("migration for lport %s not found", port_id)
            return

        port_migration = jsonutils.loads(migration_json)
        return port_migration

    def delete_lport_migration(self, port_id):
        self.driver.delete_key('lport_migration', port_id)

    def notify_migration_event(self, port_id, lport):
        lport_json = jsonutils.dumps(lport.lport)
        self._send_db_change_event('lport_migration', port_id, 'migrate',
                                   lport_json, topic=lport.lport['topic'])

    def create(self, obj, skip_send_event=False):
        """Create the provided object in the database and publish an event
           about its creation.
        """
        model = type(obj)
        obj.on_create_pre()
        serialized_obj = obj.to_json()
        topic = _get_topic(obj)
        self.driver.create_key(model.table_name, obj.id,
                               serialized_obj, topic)
        if not skip_send_event:
            self._send_db_change_event(model.table_name, obj.id, 'create',
                                       serialized_obj, topic)

    def update(self, obj, skip_send_event=False):
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
        if not skip_send_event:
            self._send_db_change_event(model.table_name, full_obj.id, 'set',
                                       serialized_obj, topic)

    def delete(self, obj, skip_send_event=False):
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
                    'Could not find object %(id)s to delete in %(table)s',
                    extra={'id': id, 'table': model.table_name})

        if not skip_send_event:
            self._send_db_change_event(model.table_name, obj.id, 'delete',
                                       obj.id, topic)

    def get(self, lean_obj):
        """Retrieve a model instance from the database. This function uses
           lean_obj to deduce ID and model type

           >>> nb_api.get(Chassis(id="one"))
           Chassis(id="One", ip="192.168.121.22", tunnel_types=["vxlan"])

        """
        if mproxy.is_model_proxy(lean_obj):
            lean_obj = lean_obj.get_proxied_model()(id=lean_obj.id)
        model = type(lean_obj)
        try:
            serialized_obj = self.driver.get_key(
                model.table_name,
                lean_obj.id,
                _get_topic(lean_obj),
            )
        except df_exceptions.DBKeyNotFound:
            LOG.exception(
                'Could not get object %(id)s from table %(table)s',
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
