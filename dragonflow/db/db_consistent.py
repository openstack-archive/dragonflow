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

import six
import time

from oslo_config import cfg
from oslo_log import log

from dragonflow._i18n import _LE, _LW
from dragonflow.common import utils as df_utils
from dragonflow.db.api_nb import OvsPort

LOG = log.getLogger(__name__)


df_controller_db_tables = [
    'lswitch',
    'port',
    'router',
    'floatingip',
    'secgroup',
    'publisher'
]


class DBConsistent(object):

    def __init__(self, topology, nb_api, db_store, controller):
        self.topology = topology
        self.nb_api = nb_api
        self.db_store = db_store
        self.controller = controller
        self.db_sync_time = cfg.CONF.df.db_sync_time
        self._daemon = df_utils.DFDaemon()
        self.lswitch_cache = {}
        self.port_cache = {}
        self.router_cache = {}
        self.secgroup_cache = {}
        self.fip_cache = {}
        self.publisher_cache = {}
        self._table_name_mapping = {
            'lswitch': self.lswitch_cache,
            'port': self.port_cache,
            'router': self.router_cache,
            'floatingip': self.fip_cache,
            'secgroup': self.secgroup_cache,
            'publisher': self.publisher_cache
        }

    def process(self, direct):
        self.check_topology_info()
        self.process_db_tables_comparison(direct)

    def run(self):
        while True:
            try:
                self.process(False)
                time.sleep(self.db_sync_time)
            except Exception as e:
                LOG.error(_LE("Exception occurred : %s") % e)
            finally:
                time.sleep(self.db_sync_time)

    def daemonize(self):
        return self._daemon.daemonize(self.run)

    def stop(self):
        return self._daemon.stop()

    def check_topology_info(self):
        new_ovs_to_lport_mapping = {}
        add_ovs_to_lport_mapping = {}
        delete_ovs_to_lport_mapping = self.topology.ovs_to_lport_mapping
        for key, ovs_port in six.iteritems(self.topology.ovs_ports):
            if ovs_port.get_type() == OvsPort.TYPE_VM:
                lport_id = ovs_port.get_iface_id()
                lport = self.topology._get_lport(lport_id)
                if lport is None:
                    LOG.warning(_LW("No logical port found for ovs port: %s")
                                % str(ovs_port))
                    continue
                topic = lport.get_topic()
                new_ovs_to_lport_mapping[key] = {'lport_id': lport_id,
                                                  'topic': topic}
                if delete_ovs_to_lport_mapping.get(key):
                    del delete_ovs_to_lport_mapping[key]
                else:
                    add_ovs_to_lport_mapping[key] = {'lport_id': lport_id,
                                                  'topic': topic}
        self.topology.ovs_to_lport_mapping = new_ovs_to_lport_mapping
        for value in add_ovs_to_lport_mapping.values():
            lport_id = value['lport_id']
            topic = value['topic']
            self.topology._add_to_topic_subscribed(topic, lport_id)

        for value in delete_ovs_to_lport_mapping.values():
            lport_id = value['lport_id']
            topic = value['topic']
            self.topology._del_from_topic_subscribed(topic, lport_id)

    def process_db_tables_comparison(self, direct):
        self.controller.register_chassis()
        self.controller.create_tunnels()
        tenants = self.topology.topic_subscribed.keys()
        for table in df_controller_db_tables:
            try:
                self.handle_data_comparison(tenants, table, direct)
            except Exception as e:
                LOG.error(_LE("Exception occurred when"
                              "handling db comparison: %s") % e)

    def _process_object(self, table, action, df_object, local_object):
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

    def _build_cache_obj(self, table, action, df_version, local_version):
        if table == 'lswitch':
            retObj = LogicSwitchCacheObj(action, df_version, local_version)
        elif table == 'port':
            retObj = PortCacheObj(action, df_version, local_version)
        elif table == 'router':
            retObj = RouterCacheObj(action, df_version, local_version)
        elif table == 'secgroup':
            retObj = SecGroupCacheObj(action, df_version, local_version)
        elif table == 'floatingip':
            retObj = FloatingIpCacheObj(action, df_version, local_version)
        elif table == 'publisher':
            retObj = PublisherCacheObj(action, df_version, local_version)
        return retObj

    def _verify_object(self, table, id, action, df_object, local_object):
        if df_object:
            df_version = df_object.get_version()
        else:
            df_version = None

        if local_object:
            local_version = local_object.get_version()
        else:
            local_version = None

        table_cache = self._table_name_mapping.get(table)
        old_cache_obj = table_cache.get(id)
        if not old_cache_obj or old_cache_obj.get_action() != action:
            cache_obj = self._build_cache_obj(
                    table, action, df_version, local_version)
            table_cache[id] = cache_obj
            return

        old_df_version = old_cache_obj.get_df_version()
        old_local_version = old_cache_obj.get_local_version()
        if action == 'create':
            if df_version >= old_df_version:
                self._process_object(table, 'create', df_object, None)
                del table_cache[id]
            return
        elif action == 'update':
            if df_version < old_df_version:
                return
            if local_version <= old_local_version:
                self._process_object(table, 'update', df_object, None)
                del table_cache[id]
            else:
                cache_obj = self._build_cache_obj(
                    table, action, df_version, local_version)
                table_cache[id] = cache_obj
        else:
            self._process_object(table, 'delete', None, local_object)
            del table_cache[id]

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

    def _compare_df_and_local_data(self, table, df_objects, local_objects, direct):
        for df_object in df_objects[:]:
            find_same_obj = False
            df_id = df_object.get_id()
            df_version = df_object.get_version()
            for local_object in local_objects[:]:
                local_id = local_object.get_id()
                if df_id != local_id:
                    continue
                else:
                    find_same_obj = True
                    local_version = local_object.get_version()
                    if df_version > local_version:
                        if direct:
                            self._process_object(
                                    table, 'update', df_object, None)
                        else:
                            self._verify_object(
                                    table, df_id, 'update',
                                    df_object, local_object)
                    local_objects.remove(local_object)
                    break
            if not find_same_obj:
                if direct:
                    self._process_object(table, 'create', df_object, None)
                else:
                    self._verify_object(table, df_id,
                                        'create', df_object, None)

        for local_object in local_objects:
            if direct:
                self._process_object(table, 'delete', None, local_object)
            else:
                self._verify_object(table, local_object.get_id(),
                                     'delete', None, local_object)

    def handle_data_comparison(self, tenants, table, direct):
        if table == 'publisher':
            df_objects, local_objects = self._get_df_and_local_objects(None, table)
            self._compare_df_and_local_data(table, df_objects, local_objects, direct)
            return
        for topic in tenants:
            df_objects, local_objects = self._get_df_and_local_objects(topic, table)
            self._compare_df_and_local_data(table, df_objects, local_objects, direct)


class CacheObject(object):
    def __init__(self, action, df_version, local_version):
        self.action = action
        self.df_version = df_version
        self.local_version = local_version

    def get_action(self):
        return self.action

    def get_df_version(self):
        return  self.df_version

    def get_local_version(self):
        return  self.local_version


class LogicSwitchCacheObj(CacheObject):
    def __init__(self, action, df_version, local_version):
        super(LogicSwitchCacheObj, self).__init__(
                action, df_version, local_version)


class PortCacheObj(CacheObject):
    def __init__(self, action, df_version, local_version):
        super(PortCacheObj, self).__init__(
                action, df_version, local_version)


class RouterCacheObj(CacheObject):
    def __init__(self, action, df_version, local_version):
        super(RouterCacheObj, self).__init__(
                action, df_version, local_version)


class SecGroupCacheObj(CacheObject):
    def __init__(self, action, df_version, local_version):
        super(SecGroupCacheObj, self).__init__(
                action, df_version, local_version)


class FloatingIpCacheObj(CacheObject):
    def __init__(self, action, df_version, local_version):
        super(FloatingIpCacheObj, self).__init__(
                action, df_version, local_version)


class PublisherCacheObj(CacheObject):
    def __init__(self, action, df_version, local_version):
        super(PublisherCacheObj, self).__init__(
                action, df_version, local_version)
