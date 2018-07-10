# Copyright (c) 2015 OpenStack Foundation.
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
import itertools
import sys
import time

from eventlet import queue
from oslo_log import log
from oslo_service import loopingcall
from ryu import cfg as ryu_cfg

from dragonflow.common import exceptions
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller.common import constants as ctrl_const
from dragonflow.controller import df_config
from dragonflow.controller import service
from dragonflow.controller import topology
from dragonflow.db import api_nb
from dragonflow.db import db_common
from dragonflow.db import db_store
from dragonflow.db import model_framework
from dragonflow.db import model_proxy
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.db.models import mixins
from dragonflow.db import sync


LOG = log.getLogger(__name__)


class DfLocalController(object):

    def __init__(self, chassis_name, nb_api):
        self.db_store = db_store.get_instance()
        self._queue = queue.PriorityQueue()
        # pending_id -> (model, pender_id)
        #       'pending_id' is the ID of the object for which we are waiting.
        #       'model' and 'pender_id' are the model and the ID of the object
        #       which is waiting for the object described by 'pending_id'
        self._pending_objects = collections.defaultdict(set)

        self.chassis_name = chassis_name
        self.nb_api = nb_api
        self.nb_api.set_db_change_callback(self.db_change_callback)
        self.ip = cfg.CONF.df.local_ip
        # Virtual tunnel port support multiple tunnel types together
        self.tunnel_types = cfg.CONF.df.tunnel_types
        self.switch_backend = df_utils.load_driver(
            cfg.CONF.df.switch_backend,
            df_utils.DF_SWITCH_BACKEND_DRIVER_NAMESPACE,
            nb_api, cfg.CONF.df.management_ip)

        self.topology = None
        self.enable_selective_topo_dist = \
            cfg.CONF.df.enable_selective_topology_distribution
        self._sync = sync.Sync(
            nb_api=self.nb_api,
            update_cb=self.update,
            delete_cb=self.delete,
            selective=self.enable_selective_topo_dist,
        )
        self._sync_pulse = loopingcall.FixedIntervalLoopingCall(
            self._submit_sync_event)

        self.sync_rate_limiter = df_utils.RateLimiter(
                max_rate=1, time_unit=db_common.DB_SYNC_MINIMUM_INTERVAL)

    def db_change_callback(self, table, key, action, value, topic=None):
        update = db_common.DbUpdate(table, key, action, value, topic=topic)
        LOG.debug("Pushing Update to Queue: %s", update)
        self._queue.put(update)
        time.sleep(0)

    def process_changes(self):
        while True:
            next_update = self._queue.get(block=True)
            LOG.debug("Event update: %s", next_update)
            self.nb_api._notification_cb(next_update)
            self._queue.task_done()

    def run(self):
        self.switch_backend.initialize(self.db_change_callback)
        self.nb_api.register_notification_callback(self._handle_update)
        self.topology = topology.Topology(self,
                                          self.enable_selective_topo_dist)
        self._sync_pulse.start(
            interval=cfg.CONF.df.db_sync_time,
            initial_delay=cfg.CONF.df.db_sync_time,
        )

        self.switch_backend.start()
        self._register_models()
        self.register_chassis()
        self.sync()
        self.process_changes()

    def _submit_sync_event(self):
        self.db_change_callback(None, None,
                                ctrl_const.CONTROLLER_SYNC, None)

    def _register_models(self):
        ignore_models = self.switch_backend.sync_ignore_models()
        for model in model_framework.iter_models_by_dependency_order():
            # FIXME (dimak) generalize sync to support non-northbound models
            # Adding OvsPort will cause sync to delete all OVS ports
            # periodically
            if model not in ignore_models:
                self._sync.add_model(model)

    def sync(self):
        self.topology.check_topology_info()
        self._sync.sync()

    def register_topic(self, topic):
        self.nb_api.subscriber.register_topic(topic)
        self._sync.add_topic(topic)

    def unregister_topic(self, topic):
        self.nb_api.subscriber.unregister_topic(topic)
        self._sync.remove_topic(topic)

    def _get_ports_by_chassis(self, chassis):
        return self.db_store.get_all(
            l2.LogicalPort(
                binding=l2.PortBinding(
                    type=l2.BINDING_CHASSIS,
                    chassis=chassis.id,
                ),
            ),
            index=l2.LogicalPort.get_index('chassis_id'),
        )

    def update_chassis(self, chassis):
        self.db_store.update(chassis)
        remote_chassis_name = chassis.id
        if self.chassis_name == remote_chassis_name:
            return

        # Notify about remote port update
        for port in self._get_ports_by_chassis(chassis):
            self.update(port)

    def delete_chassis(self, chassis):
        LOG.info("Deleting remote ports in remote chassis %s", chassis.id)
        # Chassis is deleted, there is no reason to keep the remote port
        # in it.
        for port in self._get_ports_by_chassis(chassis):
            self.delete(port)
        self.db_store.delete(chassis)

    def register_chassis(self):
        # Get all chassis from nb db to db store.
        for c in self.nb_api.get_all(core.Chassis):
            self.db_store.update(c)

        old_chassis = self.db_store.get_one(
            core.Chassis(id=self.chassis_name))

        chassis = core.Chassis(
            id=self.chassis_name,
            ip=self.ip,
            tunnel_types=self.tunnel_types,
        )
        if cfg.CONF.df.external_host_ip:
            chassis.external_host_ip = cfg.CONF.df.external_host_ip

        self.db_store.update(chassis)

        # REVISIT (dimak) Remove skip_send_event once there is no bind conflict
        # between publisher service and the controoler, see bug #1651643
        if old_chassis is None:
            self.nb_api.create(chassis, skip_send_event=True)
        elif old_chassis != chassis:
            self.nb_api.update(chassis, skip_send_event=True)

    def update_publisher(self, publisher):
        self.db_store.update(publisher)
        LOG.info('Registering to new publisher: %s', str(publisher))
        self.nb_api.subscriber.register_listen_address(publisher.uri)

    def delete_publisher(self, publisher):
        LOG.info('Deleting publisher: %s', str(publisher))
        self.nb_api.subscriber.unregister_listen_address(publisher.uri)
        self.db_store.delete(publisher)

    def switch_sync_finished(self):
        self.switch_backend.switch_sync_finished()

    def switch_sync_started(self):
        self.switch_backend.switch_sync_started()

    def _is_newer(self, obj, cached_obj):
        '''Check wether obj is newer than cached_on.

        If obj is a subtype of Version mixin we can use is_newer_than,
        otherwise we assume that our NB-received object is always newer than
        the cached copy.
        '''
        try:
            return obj.is_newer_than(cached_obj)
        except AttributeError:
            return obj != cached_obj

    def update_model_object(self, obj):
        original_obj = self.db_store.get_one(obj)

        if not self._is_newer(obj, original_obj):
            return

        self.db_store.update(obj)

        if original_obj is None:
            if _has_basic_events(obj):
                obj.emit_created()
        else:
            if _has_basic_events(obj):
                obj.emit_updated(original_obj)

    def delete_model_object(self, obj):
        # Retrieve full object (in case we only got Model(id='id'))
        org_obj = self.db_store.get_one(obj)
        if org_obj:
            if _has_basic_events(org_obj):
                org_obj.emit_deleted()
            self.db_store.delete(org_obj)
        else:
            # NOTE(nick-ma-z): Ignore the null object because
            # it has been deleted before.
            pass

    def get_nb_api(self):
        return self.nb_api

    def get_chassis_name(self):
        return self.chassis_name

    # TODO(snapiri): We should not have ovs here
    # TODO(snapiri): This should be part of the interface
    def notify_port_status(self, ovs_port, status):
        self.switch_backend.notify_port_status(ovs_port, status)

    def _get_delete_handler(self, table):
        method_name = 'delete_{0}'.format(table)
        return getattr(self, method_name, self.delete_model_object)

    def update(self, obj):
        handler = getattr(
            self,
            'update_{0}'.format(obj.table_name),
            self.update_model_object,
        )
        return handler(obj)

    def delete(self, obj):
        handler = self._get_delete_handler(obj.table_name)
        return handler(obj)

    def delete_by_id(self, model, obj_id):
        # FIXME (dimak) Probably won't be needed once we're done porting
        return self.delete(model(id=obj_id))

    def _handle_update(self, update):
        try:
            self._handle_db_change(update)
        except Exception as e:
            if "ofport is 0" not in str(e):
                LOG.exception(e)
            if not self.sync_rate_limiter():
                self.sync()

    def _handle_db_change(self, update):
        action = update.action
        if action == ctrl_const.CONTROLLER_REINITIALIZE:
            self.db_store.clear()
            self.switch_backend.initialize(self.db_change_callback)
            self.sync()
        elif action == ctrl_const.CONTROLLER_SYNC:
            self.sync()
        elif action == ctrl_const.CONTROLLER_DBRESTART:
            self.nb_api.db_recover_callback()
        elif action == ctrl_const.CONTROLLER_SWITCH_SYNC_FINISHED:
            self.switch_sync_finished()
        elif action == ctrl_const.CONTROLLER_SWITCH_SYNC_STARTED:
            self.switch_sync_started()
        elif action == ctrl_const.CONTROLLER_LOG:
            LOG.info('Log event: %s', str(update))
        elif update.table is not None:
            try:
                model_class = model_framework.get_model(update.table)
            except KeyError:
                # Model class not found, possibly update was not about a model
                LOG.warning('Unknown table %s', update.table)
            else:
                if action == 'delete':
                    self.delete_by_id(model_class, update.key)
                else:
                    obj = model_class.from_json(update.value)
                    self._send_updates_for_object(obj)
        else:
            LOG.warning('Unfamiliar update: %s', str(update))

    def _get_model(self, obj):
        if model_proxy.is_model_proxy(obj):
            return obj.get_proxied_model()
        return type(obj)

    def _send_updates_for_object(self, obj):
        try:
            references = self.get_model_references_deep(obj)
        except exceptions.ReferencedObjectNotFound as e:
            proxy = e.kwargs['proxy']
            reference_id = proxy.id
            model = self._get_model(obj)
            self._pending_objects[reference_id].add((model, obj.id))
        else:
            queue = itertools.chain(reversed(references), (obj,))
            self._send_update_events(queue)
            self._send_pending_events(obj)

    def _send_pending_events(self, obj):
        try:
            pending = self._pending_objects.pop(obj.id)
        except KeyError:
            return  # Nothing to do
        for model, item_id in pending:
            lean_obj = model(id=item_id)
            item = self.nb_api.get(lean_obj)
            self._send_updates_for_object(item)

    def get_model_references_deep(self, obj):
        """
        Return a tuple of all model instances referenced by the given model
        instance, including indirect references. e.g. if an lport references
        a network, and that network references a QoS policy, then both are
        returned in the iterator.

        Raises a ReferencedObjectNotFound exception if a referenced model
        cannot be found in the db_store or NB DB.

        :param obj: Model instance
        :type obj:  model_framework.ModelBase
        :return:    iterator
        :raises:    exceptions.ReferencedObjectNotFound
        """
        return tuple(self.iter_model_references_deep(obj))

    def iter_model_references_deep(self, obj):
        """
        Return an iterator on all model instances referenced by the given model
        instance, including indirect references. e.g. if an lport references
        a network, and that network references a QoS policy, then both are
        returned in the iterator.

        Raises a ReferencedObjectNotFound exception upon a referenced model
        cannot be found in the db_store or NB DB. The exception is thrown
        when that object is reached by the iterator, allowing other objects
        to be processed. If you need to verify all objects can be referenced,
        use 'get_model_references_deep'.

        :param obj: Model instance
        :type obj:  model_framework.ModelBase
        :return:    iterator
        :raises:    exceptions.ReferencedObjectNotFound
        """
        seen = set()
        queue = collections.deque((obj,))
        while queue:
            item = queue.pop()
            if item.id in seen:
                continue
            seen.add(item.id)
            if model_proxy.is_model_proxy(item):
                # NOTE(oanson) _dereference raises an exception for unknown
                # objectes, i.e. objects not found in the NB DB.
                item = self._dereference(item)
                yield item
            for submodel in item.iter_submodels():
                queue.append(submodel)

    def _dereference(self, reference):
        """
        Dereference a model proxy object. Return first from the db_store, and
        if it is not there, from the NB DB. Raise a ReferencedObjectNotFound
        exception if it is not in the NB DB either.

        :param reference: Model instance
        :type reference:  model_framework.ModelBase
        :return:          iterator
        :raises:          exceptions.ReferencedObjectNotFound
        """
        item = reference.get_object()
        if item is None:
            item = self.nb_api.get(reference)
        if item is None:
            raise exceptions.ReferencedObjectNotFound(proxy=reference)
        return item

    def _send_update_events(self, iterable):
        for instance in iterable:
            self.update(instance)


def _has_basic_events(obj):
    return isinstance(obj, mixins.BasicEvents)


def init_ryu_config():
    ryu_cfg.CONF(project='ryu', args=[])
    ryu_cfg.CONF.ofp_listen_host = cfg.CONF.df_ryu.of_listen_address
    ryu_cfg.CONF.ofp_tcp_listen_port = cfg.CONF.df_ryu.of_listen_port


# Run this application like this:
# python df_local_controller.py <chassis_unique_name>
# <local ip address> <southbound_db_ip_address>
def main():
    df_config.init(sys.argv[1:])
    chassis_name = cfg.CONF.host
    df_config.init(sys.argv)

    init_ryu_config()
    nb_api = api_nb.NbApi.get_instance()
    controller = DfLocalController(chassis_name, nb_api)
    service.register_service('df-local-controller', nb_api)
    controller.run()
