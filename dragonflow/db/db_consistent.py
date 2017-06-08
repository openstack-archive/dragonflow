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

from dragonflow.common import utils as df_utils

LOG = log.getLogger(__name__)

MIN_SYNC_INTERVAL_TIME = 60


def _get_version(obj):
    return getattr(obj, 'version', None)


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

    def handle_update(self, obj):
        self._update_handler(obj)

    def handle_delete(self, obj_id):
        self._delete_handler(self._model, obj_id)

    @classmethod
    def create_using_controller(cls, model, controller):
        return cls(
            model=model,
            db_store_func=functools.partial(
                controller.db_store.get_all_by_topic,
                model,
            ),
            nb_api_func=functools.partial(
                controller.nb_api.get_all,
                model,
            ),
            update_handler=controller.update,
            delete_handler=controller.delete_by_id,
        )


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
                LOG.exception("Exception occurred when"
                              "handling db comparison: %s", e)

    def _verify_object(self, handler, action, df_object, local_object=None):
        """Verify the object status and judge whether to create/update/delete
        the object or not, we'll use twice comparison to verify the status,
        first comparison result will be stored in the cache and if second
        comparison result is still consistent with the cache, we can make
        sure the object status

        :param handler: Handler of the model
        :param action:  Operate action(create/update/delete)
        :param df_object:  Object from df db
        :param local_object:  Object from local cache
        """
        df_version = _get_version(df_object)
        local_version = _get_version(local_object)

        if df_object is not None:
            obj_id = df_object.id
        else:
            obj_id = local_object.id

        old_cache_obj = handler.cache.get(obj_id)
        if not old_cache_obj or old_cache_obj.get_action() != action:
            cache_obj = CacheObject(action, df_version, local_version)
            handler.cache[obj_id] = cache_obj
            return

        old_df_version = old_cache_obj.get_df_version()
        old_local_version = old_cache_obj.get_local_version()
        if action == 'create':
            if df_version >= old_df_version:
                handler.handle_update(df_object)
                del handler.cache[obj_id]
            return
        elif action == 'update':
            if df_version < old_df_version:
                return
            if local_version <= old_local_version:
                handler.handle_update(df_object)
                del handler.cache[obj_id]
            else:
                cache_obj = CacheObject(action, df_version, local_version)
                handler.cache[obj_id] = cache_obj
        elif action == 'delete':
            handler.handle_delete(obj_id)
            del handler.cache[obj_id]
        else:
            LOG.warning('Unknown action %s in db consistent', action)

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
        local_object_map = {
            o.id: o for o in handler.get_db_store_objects(topic)
        }
        df_objects = handler.get_nb_db_objects(topic)

        for df_object in df_objects[:]:
            df_id = df_object.id
            df_version = _get_version(df_object)

            if df_version is None:
                LOG.error("Version is None in df_object: %s", df_object)
                continue
            local_object = local_object_map.pop(df_id, None)
            if local_object:
                local_version = _get_version(local_object)
                if local_version is None:
                    LOG.debug("Version is None in local_object: %s",
                              local_object)
                    handler.handle_update(df_object)
                elif df_version > local_version:
                    LOG.debug("Find a newer version df object: %s", df_object)
                    if direct:
                        handler.handle_update(df_object)
                    else:
                        self._verify_object(
                            handler, 'update', df_object, local_object)
            else:
                LOG.debug("Find an additional df object: %s", df_object)
                if direct:
                    handler.handle_update(df_object)
                else:
                    self._verify_object(handler, 'create', df_object)

        for local_object in local_object_map.values():
            LOG.debug("Find a redundant local object: %s", local_object)
            if direct:
                handler.handle_delete(local_object.id)
            else:
                self._verify_object(handler, 'delete', None, local_object)

    def handle_data_comparison(self, tenants, handler, direct):
        for topic in tenants:
            self._compare_df_and_local_data(handler, topic, direct)


class CacheObject(object):
    def __init__(self, action, df_version, local_version):
        self.action = action
        self.df_version = df_version
        self.local_version = local_version

    def get_action(self):
        return self.action

    def get_df_version(self):
        return self.df_version

    def get_local_version(self):
        return self.local_version
