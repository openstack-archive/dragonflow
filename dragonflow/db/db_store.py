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
import copy
import threading

import six

from dragonflow.db import models


class TenantDbStore(object):

    def __init__(self):
        self.lswitchs = {}
        self.ports = {}
        self.local_ports = {}
        self.routers = {}
        self.floatingips = {}
        self.secgroups = {}
        self.publishers = {}
        self.qos_policies = {}
        self.lock = threading.Lock()
        self._table_name_mapping = {
            models.LogicalSwitch.table_name: self.lswitchs,
            models.LogicalPort.table_name: self.ports,
            'local_ports': self.local_ports,
            models.LogicalRouter.table_name: self.routers,
            models.Floatingip.table_name: self.floatingips,
            models.SecurityGroup.table_name: self.secgroups,
            models.Publisher.table_name: self.publishers,
            models.QosPolicy.table_name: self.qos_policies,
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


class DbStore(object):

    def __init__(self):
        self.tenant_dbs = collections.defaultdict(TenantDbStore)
        self.chassis = {}
        self.remote_chassis_lport_map = {}

    def get(self, table_name, key, topic):
        if topic:
            return self.tenant_dbs[topic].get(table_name, key)
        for tenant_db in six.itervalues(self.tenant_dbs):
            value = tenant_db.get(table_name, key)
            if value:
                return value

    def keys(self, table_name, topic):
        if topic:
            return self.tenant_dbs[topic].keys(table_name)
        result = []
        for tenant_db in six.itervalues(self.tenant_dbs):
            result.extend(tenant_db.keys(table_name))
        return result

    def values(self, table_name, topic):
        if topic:
            return self.tenant_dbs[topic].values(table_name)
        result = []
        for tenant_db in six.itervalues(self.tenant_dbs):
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
            for tenant_db in six.itervalues(self.tenant_dbs):
                if tenant_db.pop(table_name, key):
                    break

    def get_unique_key_by_id(self, table_name, key, topic=None):
        table_item = self.get(table_name, key, topic)
        if table_item:
            return table_item.get_unique_key()

    def get_lports_by_remote_chassis(self, chassis):
        return self.remote_chassis_lport_map.get(chassis)

    def add_remote_chassis_lport(self, chassis, lport_id):
        lport_ids = self.remote_chassis_lport_map.get(chassis)
        if not lport_ids:
            self.remote_chassis_lport_map[chassis] = {lport_id}
        else:
            lport_ids.add(lport_id)

    def del_remote_chassis_lport(self, chassis, lport_id):
        lport_ids = self.remote_chassis_lport_map.get(chassis)
        if lport_ids:
            lport_ids.remove(lport_id)

    def del_remote_chassis(self, chassis):
        del self.remote_chassis_lport_map[chassis]

    def update_lswitch(self, id, lswitch, topic=None):
        self.set(models.LogicalSwitch.table_name, id, lswitch, topic)

    def get_lswitch(self, id, topic=None):
        return self.get(models.LogicalSwitch.table_name, id, topic)

    def delete_lswitch(self, id, topic=None):
        self.delete(models.LogicalSwitch.table_name, id, topic)

    def get_lport_keys(self, topic=None):
        return self.keys(models.LogicalPort.table_name, topic)

    def get_lswitch_keys(self, topic=None):
        return self.keys(models.LogicalSwitch.table_name, topic)

    def get_lrouter_keys(self, topic=None):
        return self.keys(models.LogicalRouter.table_name, topic)

    def get_floatingip_keys(self, topic=None):
        return self.keys(models.Floatingip.table_name, topic)

    def update_lport(self, port_id, port, is_local, topic=None):
        if not topic:
            topic = port.get_topic()
        if is_local:
            tenant_db = self.tenant_dbs[topic]
            with tenant_db.lock:
                tenant_db.ports[port_id] = port
                tenant_db.local_ports[port_id] = port
        else:
            self.set(models.LogicalPort.table_name, port_id, port, topic)

    def get_lport(self, port_id, topic=None):
        return self.get(models.LogicalPort.table_name, port_id, topic)

    def get_all_lports(self, topic=None):
        return self.values(models.LogicalPort.table_name, topic)

    def get_ports_by_chassis(self, chassis_id, topic=None):
        lports = self.get_all_lports(topic)
        ret_lports = []
        for lport in lports:
            if lport.get_chassis() == chassis_id:
                ret_lports.append(lport)
        return ret_lports

    def delete_lport(self, port_id, is_local, topic=None):
        if is_local:
            if not topic:
                topic = self.get_lport(port_id).get_topic()
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

    def update_lrouter(self, router_id, router, topic=None):
        self.set(models.LogicalRouter.table_name, router_id, router, topic)

    def delete_lrouter(self, id, topic=None):
        self.delete(models.LogicalRouter.table_name, id, topic)

    def get_lrouter(self, router_id, topic=None):
        return self.get(models.LogicalRouter.table_name, router_id, topic)

    def get_ports_by_network_id(self, lswitch_id, topic=None):
        ports = self.values(models.LogicalPort.table_name, topic)
        return [port for port in ports if port.get_lswitch_id() == lswitch_id]

    def get_router_by_router_interface_mac(self, interface_mac, topic=None):
        routers = self.values(models.LogicalRouter.table_name, topic)
        for router in routers:
            for port in router.get_ports():
                if port.get_mac() == interface_mac:
                    return router

    def get_all_lrouters(self, topic=None):
        return self.values(models.LogicalRouter.table_name, topic)

    def update_secgroup(self, secgroup_id, secgroup, topic=None):
        self.set(models.SecurityGroup.table_name, secgroup_id, secgroup, topic)

    def delete_secgroup(self, id, topic=None):
        self.delete(models.SecurityGroup.table_name, id, topic)

    def get_secgroup(self, secgroup_id, topic=None):
        return self.get(models.SecurityGroup.table_name, secgroup_id, topic)

    def get_all_secgroups(self, topic=None):
        return self.values(models.SecurityGroup.table_name, topic)

    def get_secgroup_keys(self, topic=None):
        return self.keys(models.SecurityGroup.table_name, topic)

    def get_all_lswitches(self, topic=None):
        return self.values(models.LogicalSwitch.table_name, topic)

    def update_floatingip(self, floatingip_id, floatingip, topic=None):
        self.set(models.Floatingip.table_name,
                 floatingip_id, floatingip, topic)

    def get_floatingip(self, floatingip_id, topic=None):
        return self.get(models.Floatingip.table_name, floatingip_id, topic)

    def delete_floatingip(self, floatingip_id, topic=None):
        self.delete(models.Floatingip.table_name, floatingip_id, topic)

    def get_all_floatingips(self, topic=None):
        return self.values(models.Floatingip.table_name, topic)

    def get_floatingips_by_gateway(self, ip, topic=None):
        fip_return = []
        for fip in self.get_all_floatingips(topic):
            if fip.get_external_gateway_ip() == ip:
                fip_return.append(fip)
        return fip_return

    def check_and_update_floatingips(self, lswitch, topic=None):
        fip_return = []
        if not lswitch.is_external():
            return fip_return
        network_id = lswitch.get_id()
        for fip in self.get_all_floatingips(topic):
            if fip.get_floating_network_id() == network_id:
                update_fip = self.update_floatingip_gateway(
                    fip, lswitch)
                if update_fip:
                    fip_return.append(update_fip)
        return fip_return

    def update_floatingip_gateway(self, fip, lswitch):
        subnets = lswitch.get_subnets()
        for subnet in subnets:
            if subnet.get_cidr() == fip.get_external_cidr():
                # external gateway ip changed
                if subnet.get_gateway_ip() != fip.get_external_gateway_ip():
                    old_fip = copy.deepcopy(fip)
                    fip.set_external_gateway_ip(subnet.get_gateway_ip())
                    return (fip, old_fip)
        return None

    def get_first_floatingip(self, network_id):
        for fip in self.get_all_floatingips():
            if fip.get_floating_network_id() == network_id:
                return fip

    def set_qos_policy(self, qos_id, qos, topic=None):
        self.set(models.QosPolicy.table_name, qos_id, qos, topic)

    def get_qos_policy(self, qos_id, topic=None):
        return self.get(models.QosPolicy.table_name, qos_id, topic)

    def delete_qos_policy(self, qos_id, topic=None):
        self.delete(models.QosPolicy.table_name, qos_id, topic)

    def get_qos_policy_keys(self, topic=None):
        return self.keys(models.QosPolicy.table_name, topic)

    def get_qos_policies(self, topic=None):
        return self.values(models.QosPolicy.table_name, topic)

    def update_publisher(self, uuid, publisher, topic=None):
        self.set(models.Publisher.table_name, uuid, publisher, topic)

    def get_publisher(self, uuid, topic=None):
        return self.get(models.Publisher.table_name, uuid, topic)

    def get_publishers(self, topic=None):
        return self.values(models.Publisher.table_name, topic)

    def delete_publisher(self, uuid, topic=None):
        self.delete(models.Publisher.table_name, uuid, topic)

    def update_chassis(self, chassis_id, chassis):
        self.chassis[chassis_id] = chassis

    def get_chassis(self, chassis_id):
        return self.chassis.get(chassis_id)

    def delete_chassis(self, chassis_id):
        self.chassis.pop(chassis_id, None)
