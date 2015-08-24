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
        self.routers = {}
        self.router_interface_to_key = {}
        self.lock = threading.Lock()

    # This is a mapping between global logical data path id (network/lswitch)
    # And a local assigned if for this controller
    def get_network_id(self, ldp):
        with self.lock:
            return self.networks.get(ldp)

    def set_network_id(self, ldp, net_id):
        with self.lock:
            self.networks[ldp] = net_id

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

    def set_port(self, port_id, port):
        with self.lock:
            self.ports[port_id] = port

    def get_port(self, port_id):
        with self.lock:
            return self.ports.get(port_id)

    def get_ports(self):
        with self.lock:
            return self.ports.values()

    def delete_port(self, port_id):
        with self.lock:
            del self.ports[port_id]

    def update_router(self, router_id, router):
        with self.lock:
            self.routers[router_id] = router

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

    def set_router_port_tunnel_key(self, interface_name, tunnel_key):
        with self.lock:
            self.router_interface_to_key[interface_name] = tunnel_key

    def get_router_port_tunnel_key(self, interface_name):
        with self.lock:
            return self.router_interface_to_key.get(interface_name)

    def del_router_port_tunnel_key(self, interface_name):
        with self.lock:
            del self.router_interface_to_key[interface_name]
