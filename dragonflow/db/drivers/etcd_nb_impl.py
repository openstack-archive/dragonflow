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

import etcd

from dragonflow.db import api_nb


class EtcdNbApi(api_nb.NbApi):

    def __init__(self, db_ip='127.0.0.1', db_port=4001):
        super(EtcdNbApi, self).__init__()
        self.client = None
        self.ip = db_ip
        self.port = db_port

    def initialize(self):
        self.client = etcd.Client(host=self.ip, port=self.port)

    def sync(self):
        pass

    def get_chassis(self, name):
        try:
            chassis_value = self.client.read('/chassis/' + name).value
            return EtcdChassis(chassis_value)
        except Exception:
            return None

    def get_all_chassis(self):
        res = []
        directory = self.client.get("/chassis")
        for result in directory.children:
            res.append(EtcdChassis(result.value))
        return res

    def add_chassis(self, name, ip, tunnel_type):
        chassis_value = name + ',' + ip + ',' + tunnel_type
        self.client.write('/chassis/' + name, chassis_value)

    def register_local_ports(self, chassis_name, local_ports_ids):
        directory = self.client.get("/binding")
        for binding in directory.children:
            lport = EtcdLogicalPort(binding.value)
            if lport.get_id() in local_ports_ids:
                if lport.get_chassis() == chassis_name:
                    continue
                lport.set_chassis(chassis_name)
                self.client.write('/binding/' + lport.get_id(),
                                  lport.parse_value())
            elif lport.get_chassis() == chassis_name:
                lport.set_chassis('None')
                self.client.write('/binding/' + lport.get_id(),
                                  lport.parse_value())

    def get_all_logical_ports(self):
        res = []
        directory = self.client.get("/binding")
        for binding in directory.children:
            lport = EtcdLogicalPort(binding.value)
            if lport.get_chassis() is None:
                continue
            res.append(lport)
        return res


class EtcdChassis(api_nb.Chassis):

    def __init__(self, value):
        # Entry <chassis_name, chassis_ip, chassis_tunnel_type>
        self.values = value.split(',')

    def get_name(self):
        return self.values[0]

    def get_ip(self):
        return self.values[1]

    def get_encap_type(self):
        return self.values[2]


class EtcdLogicalPort(api_nb.LogicalPort):

    def __init__(self, value):
        # Entry <chassis_name, network, lport, mac, tunnel_key>
        self.values = value.split(',')
        self.external_dict = {}

    def parse_value(self):
        return (self.values[0] + ',' + self.values[1] + ','
                + self.values[2] + ','
                + self.values[3] + ',' + self.values[4])

    def set_chassis(self, chassis):
        self.values[0] = chassis

    def get_id(self):
        return self.values[2]

    def get_mac(self):
        return self.values[3]

    def get_chassis(self):
        chassis = self.values[0]
        if chassis == 'None':
            return None
        return chassis

    def get_network_id(self):
        return self.values[1]

    def get_tunnel_key(self):
        return int(self.values[4])

    def set_external_value(self, key, value):
        self.external_dict[key] = value

    def get_external_value(self, key):
        return self.external_dict.get(key)
