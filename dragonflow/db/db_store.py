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
        self.networks = {}
        self.ports = {}
        self.routers = {}
        self.network_to_routers = {}
        self.lock = threading.Lock()

    # This is a mapping between global logical data path id (network/lswitch)
    # And a local assigned if for this controller
    def get_network_id(self, ldp):
        with self.lock:
            return self.networks.get(ldp)

    def set_network_id(self, ldp, net_id):
        with self.lock:
            self.networks[ldp] = net_id

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

    def set_router(self, router_id, router):
        with self.lock:
            self.routers[router_id] = router

    def get_router(self, router_id):
        with self.lock:
            return self.routers.get(router_id)

    def get_ports_by_network_id(self, local_network_id):
        res = []
        with self.lock:
            for port in self.ports.values():
                net_id = port.get_network_id()
                if net_id == local_network_id:
                    res.append(port)
        return res

    def get_port_by_ofport(self, ofport):
        with self.lock:
            for port in self.ports.values():
                if port.get_external_value('ofport') == ofport:
                    return port

    def get_router_by_network(self, network_id):
        with self.lock:
            router_name = self.network_to_routers.get(network_id)
            return self.routers.get(router_name)

    def attach_network_to_router(self, network_id, router):
        router_name = router.get_name()
        with self.lock:
            self.network_to_routers[network_id] = router_name

    def del_network_from_router(self, network_id):
        with self.lock:
            del self.network_to_routers[network_id]
