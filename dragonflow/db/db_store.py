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
        self.lock = threading.Lock()

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

    def add_router(self, router_id, router):
        with self.lock:
            self.routers[router_id] = router

    def get_router(self, router_id):
        with self.lock:
            return self.routers.get(router_id)
