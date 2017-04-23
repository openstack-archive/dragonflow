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
import threading

from dragonflow.db import models


class TenantDbStore(object):

    def __init__(self):
        self.ports = {}
        self.local_ports = {}
        self.floatingips = {}
        self.secgroups = {}
        self.activeports = {}
        self.lock = threading.Lock()
        self._table_name_mapping = {
            models.LogicalPort.table_name: self.ports,
            'local_ports': self.local_ports,
            models.Floatingip.table_name: self.floatingips,
            models.SecurityGroup.table_name: self.secgroups,
            models.AllowedAddressPairsActivePort.table_name: self.activeports
        }

    def _get_table_by_name(self, table_name):
        return self._table_name_mapping[table_name]

    def get(self, table_name, key):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.get(key)

    def set(self, table_name, key, value):
        table = self._get_table_by_name(table_name)
        with self.lock:
            table[key] = value

    def pop(self, table_name, key):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.pop(key, None)

    def keys(self, table_name):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.keys()

    def values(self, table_name):
        table = self._get_table_by_name(table_name)
        with self.lock:
            return table.values()

    def clear(self):
        with self.lock:
            for table_name in self._table_name_mapping:
                self._table_name_mapping[table_name].clear()


class DbStore(object):

    def __init__(self):
        self.tenant_dbs = collections.defaultdict(TenantDbStore)

    def get(self, table_name, key, topic):
        if topic:
            return self.tenant_dbs[topic].get(table_name, key)
        for tenant_db in self.tenant_dbs.values():
            value = tenant_db.get(table_name, key)
            if value:
                return value

    def keys(self, table_name, topic):
        if topic:
            return self.tenant_dbs[topic].keys(table_name)
        result = []
        for tenant_db in self.tenant_dbs.values():
            result.extend(tenant_db.keys(table_name))
        return result

    def values(self, table_name, topic):
        if topic:
            return self.tenant_dbs[topic].values(table_name)
        result = []
        for tenant_db in self.tenant_dbs.values():
            result.extend(tenant_db.values(table_name))
        return result

    def set(self, table_name, key, value, topic):
        if not topic:
            topic = value.get_topic()
        self.tenant_dbs[topic].set(table_name, key, value)

    def delete(self, table_name, key, topic):
        if topic:
            self.tenant_dbs[topic].pop(table_name, key)
        else:
            for tenant_db in self.tenant_dbs.values():
                if tenant_db.pop(table_name, key):
                    break

    def get_unique_key_by_id(self, table_name, key, topic=None):
        table_item = self.get(table_name, key, topic)
        if table_item:
            return table_item.get_unique_key()

    def get_port_keys(self, topic=None):
        return self.keys(models.LogicalPort.table_name, topic)

    def get_floatingip_keys(self, topic=None):
        return self.keys(models.Floatingip.table_name, topic)

    def set_port(self, port_id, port, is_local, topic=None):
        if not topic:
            topic = port.get_topic()
        if is_local:
            tenant_db = self.tenant_dbs[topic]
            with tenant_db.lock:
                tenant_db.ports[port_id] = port
                tenant_db.local_ports[port_id] = port
        else:
            self.set(models.LogicalPort.table_name, port_id, port, topic)

    def get_port(self, port_id, topic=None):
        return self.get(models.LogicalPort.table_name, port_id, topic)

    def get_ports(self, topic=None):
        return self.values(models.LogicalPort.table_name, topic)

    def get_ports_by_chassis(self, chassis_id, topic=None):
        lports = self.get_ports(topic)
        ret_lports = []
        for lport in lports:
            if lport.get_chassis() == chassis_id:
                ret_lports.append(lport)
        return ret_lports

    def delete_port(self, port_id, is_local, topic=None):
        if is_local:
            if not topic:
                topic = self.get_port(port_id).get_topic()
            tenant_db = self.tenant_dbs[topic]
            with tenant_db.lock:
                del tenant_db.ports[port_id]
                del tenant_db.local_ports[port_id]
        else:
            self.delete(models.LogicalPort.table_name, port_id, topic)

    def get_local_port(self, port_id, topic=None):
        return self.get('local_ports', port_id, topic)

    def get_local_ports(self, topic=None):
        return self.values('local_ports', topic)

    def get_local_port_by_name(self, port_name, topic=None):
        # TODO(oanson) This will be bad for performance
        ports = self.values('local_ports', topic)
        port_id_prefix = port_name[3:]
        for lport in ports:
            if lport.get_id().startswith(port_id_prefix):
                return lport

    def get_ports_by_network_id(self, lswitch_id, topic=None):
        ports = self.values(models.LogicalPort.table_name, topic)
        return [port for port in ports if port.get_lswitch_id() == lswitch_id]

    def update_security_group(self, secgroup_id, secgroup, topic=None):
        self.set(models.SecurityGroup.table_name, secgroup_id, secgroup, topic)

    def delete_security_group(self, id, topic=None):
        self.delete(models.SecurityGroup.table_name, id, topic)

    def get_security_group(self, secgroup_id, topic=None):
        return self.get(models.SecurityGroup.table_name, secgroup_id, topic)

    def get_security_groups(self, topic=None):
        return self.values(models.SecurityGroup.table_name, topic)

    def get_security_group_keys(self, topic=None):
        return self.keys(models.SecurityGroup.table_name, topic)

    def update_floatingip(self, floatingip_id, floatingip, topic=None):
        self.set(models.Floatingip.table_name,
                 floatingip_id, floatingip, topic)

    def get_floatingip(self, floatingip_id, topic=None):
        return self.get(models.Floatingip.table_name, floatingip_id, topic)

    def delete_floatingip(self, floatingip_id, topic=None):
        self.delete(models.Floatingip.table_name, floatingip_id, topic)

    def get_floatingips(self, topic=None):
        return self.values(models.Floatingip.table_name, topic)

    def get_active_port(self, active_port_key, topic=None):
        return self.get(models.AllowedAddressPairsActivePort.table_name,
                        active_port_key, topic)

    def update_active_port(self, active_port_key, active_port, topic=None):
        self.set(models.AllowedAddressPairsActivePort.table_name,
                 active_port_key, active_port, topic)

    def delete_active_port(self, active_port_key, topic=None):
        self.delete(models.AllowedAddressPairsActivePort.table_name,
                    active_port_key, topic)

    def get_active_ports(self, topic=None):
        return self.values(models.AllowedAddressPairsActivePort.table_name,
                           topic)

    def get_active_port_keys(self, topic=None):
        return self.keys(models.AllowedAddressPairsActivePort.table_name,
                         topic)

    def get_active_ports_by_network_id(self, network_id, topic=None):
        activeports = self.values(
            models.AllowedAddressPairsActivePort.table_name, topic)
        return [activeport for activeport in activeports
                if activeport.get_network_id() == network_id]

    def clear(self, topic=None):
        if not topic:
            for tenant_db in self.tenant_dbs.values():
                tenant_db.clear()
        else:
            self.tenant_dbs[topic].clear()
