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


class TenantDbStore(object):

    def __init__(self):
        self.lswitchs = {}
        self.ports = {}
        self.local_ports = {}
        self.routers = {}
        self.floatingips = {}
        self.secgroups = {}
        self.publishers = {}
        self.lock = threading.Lock()
        self._table_name_mapping = {
            'lswitchs': self.lswitchs,
            'ports': self.ports,
            'local_ports': self.local_ports,
            'routers': self.routers,
            'floatingips': self.floatingips,
            'secgroups': self.secgroups,
            'publishers': self.publishers,
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
        self.networks = {}

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

    # This is a mapping between global logical data path id (network/lswitch)
    # And a local assigned if for this controller
    def get_network_id(self, ldp):
        return self.networks.get(ldp, None)

    def set_network_id(self, ldp, net_id):
        self.networks[ldp] = net_id

    def del_network_id(self, ldp):
        self.networks.pop(ldp, None)

    def set_lswitch(self, id, lswitch, topic=None):
        self.set('lswitchs', id, lswitch, topic)

    def get_lswitch(self, id, topic=None):
        return self.get('lswitchs', id, topic)

    def del_lswitch(self, id, topic=None):
        self.delete('lswitchs', id, topic)

    def get_port_keys(self, topic=None):
        return self.keys('ports', topic)

    def get_lswitch_keys(self, topic=None):
        return self.keys('lswitchs', topic)

    def get_router_keys(self, topic=None):
        return self.keys('routers', topic)

    def get_floatingip_keys(self, topic=None):
        return self.keys('floatingips', topic)

    def set_port(self, port_id, port, is_local, topic=None):
        if not topic:
            topic = port.get_topic()
        if is_local:
            tenant_db = self.tenant_dbs[topic]
            with tenant_db.lock:
                tenant_db.ports[port_id] = port
                tenant_db.local_ports[port_id] = port
        else:
            self.set('ports', port_id, port, topic)

    def get_port(self, port_id, topic=None):
        return self.get('ports', port_id, topic)

    def get_ports(self, topic=None):
        return self.values('ports', topic)

    def delete_port(self, port_id, is_local, topic=None):
        if is_local:
            if not topic:
                topic = self.get_port(port_id).get_topic()
            tenant_db = self.tenant_dbs[topic]
            with tenant_db.lock:
                del tenant_db.ports[port_id]
                del tenant_db.local_ports[port_id]
        else:
            self.delete('ports', port_id, topic)

    def get_local_port(self, port_id, topic=None):
        return self.get('local_ports', port_id, topic)

    def get_local_port_by_name(self, port_name, topic=None):
        # TODO(oanson) This will be bad for performance
        ports = self.values('local_ports', topic)
        port_id_prefix = port_name[3:]
        for lport in ports:
            if lport.get_id().startswith(port_id_prefix):
                return lport

    def update_router(self, router_id, router, topic=None):
        self.set('routers', router_id, router, topic)

    def delete_router(self, id, topic=None):
        self.delete('routers', id, topic)

    def get_router(self, router_id, topic=None):
        return self.get('routers', router_id, topic)

    def get_ports_by_network_id(self, lswitch_id, topic=None):
        ports = self.values('ports', topic)
        return [port for port in ports if port.get_lswitch_id() == lswitch_id]

    def get_router_by_router_interface_mac(self, interface_mac, topic=None):
        routers = self.values('routers', topic)
        for router in routers:
            for port in router.get_ports():
                if port.get_mac() == interface_mac:
                    return router

    def get_routers(self, topic=None):
        return self.values('routers', topic)

    def update_security_group(self, secgroup_id, secgroup, topic=None):
        self.set('secgroups', secgroup_id, secgroup, topic)

    def delete_security_group(self, id, topic=None):
        self.delete('secgroups', id, topic)

    def get_security_group(self, secgroup_id, topic=None):
        return self.get('secgroups', secgroup_id, topic)

    def get_security_groups(self, topic=None):
        return self.values('secgroups', topic)

    def get_security_group_keys(self, topic=None):
        return self.keys('secgroups', topic)

    def get_lswitchs(self, topic=None):
        return self.values('lswitchs', topic)

    def update_floatingip(self, floatingip_id, floatingip, topic=None):
        self.set('floatingips', floatingip_id, floatingip, topic)

    def get_floatingip(self, floatingip_id, topic=None):
        return self.get('floatingips', floatingip_id, topic)

    def delete_floatingip(self, floatingip_id, topic=None):
        self.delete('floatingips', floatingip_id, topic)

    def get_floatingips(self, topic=None):
        return self.values('floatingips', topic)

    def get_floatingips_by_gateway(self, ip, topic=None):
        fip_return = []
        for fip in self.get_floatingips(topic):
            if fip.get_external_gateway_ip() == ip:
                fip_return.append(fip)
        return fip_return

    def check_and_update_floatingips(self, lswitch, topic=None):
        fip_return = []
        if not lswitch.is_external():
            return fip_return
        network_id = lswitch.get_id()
        for fip in self.get_floatingips(topic):
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
        for fip in self.get_floatingips():
            if fip.get_floating_network_id() == network_id:
                return fip

    def update_publisher(self, uuid, publisher, topic=None):
        self.set('publishers', uuid, publisher, topic)

    def get_publisher(self, uuid, topic=None):
        return self.get('publishers', uuid, topic)

    def delete_publisher(self, uuid, topic=None):
        self.delete('publishers', uuid, topic)
