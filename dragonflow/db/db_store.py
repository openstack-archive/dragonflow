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

import threading


class DbStore(object):

    def __init__(self):
        self.lswitchs = {}
        self.networks = {}
        self.ports = {}
        self.local_ports = {}
        self.routers = {}
        self.router_interface_to_key = {}
        self.floatingips = {}
        self.secgroups = {}
        self.lock = threading.Lock()

    # This is a mapping between global logical data path id (network/lswitch)
    # And a local assigned if for this controller
    def get_network_id(self, ldp):
        with self.lock:
            return self.networks.get(ldp)

    def set_network_id(self, ldp, net_id):
        with self.lock:
            self.networks[ldp] = net_id

    def del_network_id(self, ldp):
        with self.lock:
            del self.networks[ldp]

    def set_lswitch(self, id, lswitch):
        with self.lock:
            self.lswitchs[id] = lswitch

    def get_lswitch(self, id):
        with self.lock:
            return self.lswitchs.get(id)

    def del_lswitch(self, id):
        with self.lock:
            del self.lswitchs[id]

    def get_port_keys(self):
        with self.lock:
            return set(self.ports.keys())

    def set_port(self, port_id, port, is_local):
        with self.lock:
            self.ports[port_id] = port
            if is_local:
                self.local_ports[port_id] = port

    def get_port(self, port_id):
        with self.lock:
            return self.ports.get(port_id)

    def get_ports(self):
        with self.lock:
            return self.ports.values()

    def delete_port(self, port_id, is_local):
        with self.lock:
            del self.ports[port_id]
            if is_local:
                del self.local_ports[port_id]

    def get_local_port(self, port_id):
        with self.lock:
            return self.local_ports.get(port_id)

    def get_local_port_by_name(self, port_name):
        port_id_prefix = port_name[3:]
        for lport in self.local_ports.values():
            if lport.get_id().startswith(port_id_prefix):
                return lport

    def update_router(self, router_id, router):
        with self.lock:
            self.routers[router_id] = router

    def delete_router(self, id):
        with self.lock:
            del self.routers[id]

    def get_router(self, router_id):
        with self.lock:
            return self.routers.get(router_id)

    def get_ports_by_network_id(self, local_network_id):
        res = []
        with self.lock:
            for port in self.ports.values():
                net_id = port.get_lswitch_id()
                if net_id == local_network_id:
                    res.append(port)
        return res

    def get_router_by_router_interface_mac(self, interface_mac):
        with self.lock:
            for router in self.routers.values():
                for port in router.get_ports():
                    if port.get_mac() == interface_mac:
                        return router

    def get_routers(self):
        with self.lock:
            return self.routers.values()

    def update_security_group(self, secgroup_id, secgroup):
        with self.lock:
            self.secgroups[secgroup_id] = secgroup

    def delete_security_group(self, id):
        with self.lock:
            del self.secgroups[id]

    def get_security_group(self, secgroup_id):
        with self.lock:
            return self.secgroups.get(secgroup_id)

    def get_security_groups(self):
        with self.lock:
            return self.secgroups.values()

    def get_security_group_keys(self):
        with self.lock:
            return set(self.secgroups.keys())

    def get_lswitchs(self):
        with self.lock:
            return self.lswitchs.values()

    def update_floatingip(self, floatingip_id, floatingip):
        with self.lock:
            self.floatingips[floatingip_id] = floatingip

    def get_floatingip(self, floatingip_id):
        with self.lock:
            return self.floatingips.get(floatingip_id)

    def delete_floatingip(self, floatingip_id):
        with self.lock:
            del self.floatingips[floatingip_id]

    def get_floatingips(self):
        with self.lock:
            return self.floatingips.values()
