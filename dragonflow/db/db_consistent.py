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

import time

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LE, _LW
from dragonflow.common import utils as df_utils

LOG = log.getLogger(__name__)

MIN_SYNC_INTERVAL_TIME = 300


class CacheManager(object):
    def __init__(self):
        self._table_name_mapping = {
            'lswitch': {},
            'port': {},
            'router': {},
            'floatingip': {},
            'secgroup': {},
            'publisher': {}
        }

    def get(self, table, key):
        return self._table_name_mapping[table].get(key)

    def set(self, table, key, value):
        self._table_name_mapping[table][key] = value

    def remove(self, table, key):
        del self._table_name_mapping[table][key]

    def get_tables(self):
        return self._table_name_mapping.keys()


class DBConsistencyManager(object):

    def __init__(self, controller):
        self.topology = controller.topology
        self.nb_api = controller.nb_api
        self.db_store = controller.db_store
        self.controller = controller
        self.db_sync_time = cfg.CONF.df.db_sync_time
        if self.db_sync_time < MIN_SYNC_INTERVAL_TIME:
            self.db_sync_time = MIN_SYNC_INTERVAL_TIME
        self._daemon = df_utils.DFDaemon()
        self.cache_manager = CacheManager()

    def process(self, direct):
        self.topology.check_topology_info()
        self._process_db_tables_comparison(direct)

    def run(self):
        while True:
            time.sleep(self.db_sync_time)
            self.nb_api.db_change_callback(None, None, "db_sync", "db_sync")

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
        self.controller.create_tunnels()
        topics = self.topology.topic_subscribed.keys()
        for table in self.cache_manager.get_tables():
            try:
                self.handle_data_comparison(topics, table, direct)
            except Exception as e:
                LOG.exception(_LE("Exception occurred when"
                              "handling db comparison: %s"), e)

    def _process_object(self, table, action, df_object, local_object=None):
        if table == 'lswitch':
            if action == 'delete':
                self.controller.logical_switch_deleted(local_object.get_id())
            else:
                self.controller.logical_switch_updated(df_object)
        elif table == 'port':
            if action == 'create':
                self.controller.logical_port_created(df_object)
            elif action == 'update':
                self.controller.logical_port_updated(df_object)
            else:
                self.controller.logical_port_deleted(local_object.get_id())
        elif table == 'router':
            if action == 'delete':
                self.controller.router_deleted(local_object.get_id())
            else:
                self.controller.router_updated(df_object)
        elif table == 'secgroup':
            if action == 'delete':
                self.controller.security_group_deleted(local_object.get_id())
            else:
                self.controller.security_group_updated(df_object)
        elif table == 'floatingip':
            if action == 'delete':
                self.controller.floatingip_deleted(local_object.get_id())
            else:
                self.controller.floatingip_updated(df_object)
        elif table == 'publisher':
            if action == 'delete':
                self.controller.publisher_deleted(local_object.get_id())
            else:
                self.controller.publisher_updated(df_object)

    def _verify_object(self, table, id, action, df_object, local_object=None):
        """Verify the object status and judge whether to create/update/delete
        the object or not, we'll use twice comparison to verify the status,
        first comparison result will be stored in the cache and if second
        comparison result is still consistent with the cache, we can make
        sure the object status

        :param table:  Resource object type
        :param id:  Resource object id
        :param action:  Operate action(create/update/delete)
        :param df_object:  Object from df db
        :param local_object:  Object from local cache
        """
        df_version = df_object.get_version() if df_object else None
        local_version = local_object.get_version() if local_object else None

        old_cache_obj = self.cache_manager.get(table, id)
        if not old_cache_obj or old_cache_obj.get_action() != action:
            cache_obj = CacheObject(action, df_version, local_version)
            self.cache_manager.set(table, id, cache_obj)
            return

        old_df_version = old_cache_obj.get_df_version()
        old_local_version = old_cache_obj.get_local_version()
        if action == 'create':
            if df_version >= old_df_version:
                self._process_object(table, 'create', df_object)
                self.cache_manager.remove(table, id)
            return
        elif action == 'update':
            if df_version < old_df_version:
                return
            if local_version <= old_local_version:
                self._process_object(table, 'update', df_object)
                self.cache_manager.remove(table, id)
            else:
                cache_obj = CacheObject(action, df_version, local_version)
                self.cache_manager.set(table, id, cache_obj)
        elif action == 'delete':
            self._process_object(table, 'delete', None, local_object)
            self.cache_manager.remove(table, id)
        else:
            LOG.warning(_LW('Unknown action %s in db consistent'), action)

    def _get_df_and_local_objects(self, topic, table):
        df_objects = []
        local_objects = []
        if table == 'lswitch':
            df_objects = self.nb_api.get_all_logical_switches(topic)
            local_objects = self.db_store.get_lswitchs(topic)
        elif table == 'port':
            df_objects = self.nb_api.get_all_logical_ports(topic)
            local_objects = self.db_store.get_ports(topic)
        elif table == 'router':
            df_objects = self.nb_api.get_routers(topic)
            local_objects = self.db_store.get_routers(topic)
        elif table == 'secgroup':
            df_objects = self.nb_api.get_security_groups(topic)
            local_objects = self.db_store.get_security_groups(topic)
        elif table == 'floatingip':
            df_objects = self.nb_api.get_floatingips(topic)
            local_objects = self.db_store.get_floatingips(topic)
        elif table == 'publisher':
            df_objects = self.nb_api.get_publishers()
            local_objects = self.db_store.get_publishers()

        return df_objects, local_objects

    def _compare_df_and_local_data(
            self, table, df_objects, local_objects, direct):
        """Compare specific resource type df objects and local objects
        one by one, we could judge whether to create/update/delete
        the corresponding object.

        :param table:  Resource object type
        :param df_object:  Object from df db
        :param local_object:  Object from local cache
        :param direct:  the process model, if True, we'll do the operation
        directly after this comparison, if False, we'll go into the verify
        process which need twice comparision to do the operation.
        """
        local_object_map = {}
        for local_object in local_objects:
            local_object_map[local_object.get_id()] = local_object
        for df_object in df_objects[:]:
            df_id = df_object.get_id()
            df_version = df_object.get_version()
            if not df_version:
                LOG.error(_LE("Version is None in df_object:%s"), df_object)
                continue
            local_object = local_object_map.pop(df_id, None)
            if local_object:
                local_version = local_object.get_version()
                if not local_version:
                    self._process_object(
                                table, 'update', df_object)
                elif df_version > local_version:
                    if direct:
                        self._process_object(
                                table, 'update', df_object)
                    else:
                        self._verify_object(
                                table, df_id, 'update',
                                df_object, local_object)
            else:
                if direct:
                    self._process_object(table, 'create', df_object)
                else:
                    self._verify_object(table, df_id,
                                        'create', df_object)

        for local_object in local_object_map.values():
            if direct:
                self._process_object(table, 'delete', None, local_object)
            else:
                self._verify_object(
                        table, local_object.get_id(),
                        'delete', None, local_object)

    def _get_and_compare_df_and_local_data(self, table, direct, topic=None):
        df_objects, local_objects = self._get_df_and_local_objects(
                topic, table)
        self._compare_df_and_local_data(
                table, df_objects, local_objects, direct)

    def handle_data_comparison(self, tenants, table, direct):
        if table == 'publisher':
            self._get_and_compare_df_and_local_data(table, direct)
            return
        for topic in tenants:
            self._get_and_compare_df_and_local_data(table, direct, topic)


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
