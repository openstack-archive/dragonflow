# Copyright (c) 2015 OpenStack Foundation.
#
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


class NbApi(object):

    def initialize(self):
        pass

    def sync(self):
        pass

    def get_chassis(self, name):
        pass

    def get_all_chassis(self):
        pass

    def add_chassis(self, name, ip, tunnel_type):
        pass

    def register_local_ports(self, chassis, local_ports_id):
        pass

    def get_all_logical_ports(self):
        pass


class Chassis(object):

    def get_name(self):
        pass

    def get_ip(self):
        pass

    def get_encap_type(self):
        pass


class LogicalPort(object):

    def get_id(self):
        pass

    def get_mac(self):
        pass

    def get_chassis(self):
        pass

    def get_network_id(self):
        pass

    def get_tunnel_key(self):
        pass

    def set_external_value(self, key, value):
        pass

    def get_external_value(self, key):
        pass

