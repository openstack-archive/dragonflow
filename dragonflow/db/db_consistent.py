# Copyright (c) 2016 OpenStack Foundation.
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
import functools
import time

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LE
from dragonflow.common import utils as df_utils

LOG = log.getLogger(__name__)

MIN_SYNC_INTERVAL_TIME = 60


def _get_version(obj):
    return getattr(obj, 'version', None)


_CREATE = 'create'
_UPDATE = 'update'
_DELETE = 'delete'


class _CacheObject(object):
    def __init__(self, action, nb_version, local_version):
        self.action = action
        self.nb_version = nb_version
        self.local_version = local_version


class ModelHandler(object):
    '''This class encapsulates all the actions that db consistency model will
    perform on a specific model.

    This includes initiating update and delete of a model instance, and
    retrieving model objects from local cache and northbound database.
    '''
    def __init__(self, model, db_store_func, nb_api_func,
                 update_handler, delete_handler):
        self._model = model
        self._db_store_func = db_store_func
        self._nb_api_func = nb_api_func
        self._update_handler = update_handler
        self._delete_handler = delete_handler
        self.cache = {}

    def get_db_store_objects(self, topic):
        return self._db_store_func(topic)

    def get_nb_db_objects(self, topic):
        return self._nb_api_func(topic)

    @classmethod
    def create_using_controller(cls, model, controller):
        return cls(
            model=model,
            db_store_func=functools.partial(
                controller.db_store2.get_all_by_topic,
                model,
            ),
            nb_api_func=functools.partial(
                controller.nb_api.get_all,
                model,
            ),
            update_handler=controller.update,
            delete_handler=controller.delete,
        )

    def _get_cache_obj(self, action, obj_id):
        cache_obj = self.cache.get(obj_id)
        if cache_obj is None or cache_obj.action != action:
            return None

        return cache_obj

    def _add_to_cache(self, action, nb_obj=None, local_obj=None):
        obj_id = (nb_obj or local_obj).id
        self.cache[obj_id] = _CacheObject(
            action,
            _get_version(nb_obj),
            _get_version(local_obj),
        )

    def handle_create(self, direct, obj):
        if direct:
            self._update_handler(obj)
        else:
            cache_obj = self._get_cache_obj(_CREATE, obj.id)
            if cache_obj is None:
                self._add_to_cache(_CREATE, nb_obj=obj)
            else:
                self._handle_indirect_create(cache_obj, obj)

    def _handle_indirect_create(self, cache_obj, obj):
        self._update_handler(obj)
        del self.cache[obj.id]

    def handle_update(self, direct, obj, local_obj):
        if obj == local_obj:
            return

        if direct:
            self._update_handler(obj)
        else:
            cache_obj = self._get_cache_obj(_UPDATE, obj.id)
            if cache_obj is None:
                self._add_to_cache(_UPDATE, nb_obj=obj, local_obj=local_obj)
            else:
                self._handle_indirect_update(cache_obj, obj, local_obj)

    def _handle_indirect_update(self, cache_obj, obj, local_obj):
        self._update_handler(obj)
        del self.cache[obj.id]

    def handle_delete(self, direct, obj):
        if direct:
            self._delete_handler(obj)
        else:
            cache_obj = self._get_cache_obj(_DELETE, obj.id)
            if cache_obj is None:
                self._add_to_cache(_DELETE, local_obj=obj)
            else:
                self._handle_indirect_delete(cache_obj, obj)

    def _handle_indirect_delete(self, cache_obj, obj):
        self._delete_handler(obj)
        del self.cache[obj.id]


class VersionedModelHandler(ModelHandler):
    def _handle_indirect_create(self, cache_obj, obj):
        if obj.version >= cache_obj.nb_version:
            self._update_handler(obj)
            del self.cache[obj.id]

    def handle_update(self, direct, obj, local_obj):
        if not obj.is_newer_than(local_obj):
            return

        super(VersionedModelHandler, self).handle_update(direct, obj,
                                                         local_obj)

    def _handle_indirect_update(self, cache_obj, obj, local_obj):
        if obj.version < cache_obj.nb_version:
            return

        if local_obj.version <= cache_obj.local_version:
            self._update_handler(obj)
            del self.cache[obj.id]
        else:
            self._add_to_cache(_UPDATE, nb_obj=obj, local_obj=local_obj)


class DBConsistencyManager(object):

    def __init__(self, controller):
        self.topology = controller.topology
        self.nb_api = controller.nb_api
        self.controller = controller
        self.db_sync_time = cfg.CONF.df.db_sync_time
        if self.db_sync_time < MIN_SYNC_INTERVAL_TIME:
            self.db_sync_time = MIN_SYNC_INTERVAL_TIME
        self._daemon = df_utils.DFDaemon()
        self._handlers = []

    def add_handler(self, handler):
        self._handlers.append(handler)

    def process(self, direct):
        self.topology.check_topology_info()
        self._process_db_tables_comparison(direct)

    def run(self):
        while True:
            time.sleep(self.db_sync_time)
            self.nb_api.db_change_callback(None, None, "db_sync", "db_sync")
            LOG.debug("Enter db consistent processing")

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def _process_db_tables_comparison(self, direct):
        """Do the comparison and sync according to the difference between
        df db and local cache

        :param direct:  Indicate the process mode, if True, it will sync
                         the data immediately once it found the difference,
                         if False, it will do the sync job after twice data
                         comparisons.
        """
        self.controller.register_chassis()
        topics = self.topology.topic_subscribed.keys()
        for handler in self._handlers:
            try:
                self.handle_data_comparison(topics, handler, direct)
            except Exception as e:
                LOG.exception(_LE("Exception occurred when"
                              "handling db comparison: %s"), e)

    def _compare_df_and_local_data(self, handler, topic, direct):
        """Compare specific resource type df objects and local objects
        one by one, we could judge whether to create/update/delete
        the corresponding object.

        :param handler: model handler we're checking
        :param topic:  topic whose objectes we're checking
        :param direct:  the process model, if True, we'll do the operation
        directly after this comparison, if False, we'll go into the verify
        process which need twice comparison to do the operation.
        """
        local_objects = {o.id: o for o in handler.get_db_store_objects(topic)}
        local_ids = set(local_objects.keys())

        nb_objects = {o.id: o for o in handler.get_nb_db_objects(topic)}
        nb_ids = set(nb_objects.keys())

        common_ids = nb_ids.intersection(local_ids)
        deleted_ids = local_ids - common_ids
        added_ids = nb_ids - common_ids

        for obj in (local_objects[id] for id in deleted_ids):
            LOG.debug("Found a redundant local object: %r", obj)
            handler.handle_delete(direct, obj)

        for local_obj, nb_obj in (
            (local_objects[id], nb_objects[id]) for id in common_ids
        ):
            handler.handle_update(direct, nb_obj, local_obj)

        for obj in (nb_objects[id] for id in added_ids):
            LOG.debug("Found a new df object: %r", obj)
            handler.handle_create(direct, obj)

    def handle_data_comparison(self, tenants, handler, direct):
        for topic in tenants:
            self._compare_df_and_local_data(handler, topic, direct)
