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

from dragonflow.db import api_nb

from ovs.db import idl

from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import idlutils


class OvsdbNbApi(api_nb.NbApi):

    def __init__(self, ip, protocol='tcp', port='6640', timeout=10):
        super(OvsdbNbApi, self).__init__()
        self.ip = ip
        self.db_name = 'OVN_Southbound'
        self.protocol = protocol
        self.port = port
        self.timeout = timeout
        self.ovsdb = None
        self.idl = None

    def initialize(self):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))
        self.ovsdb = connection.Connection(db_connection,
                                           self.timeout,
                                           self.db_name)
        self.ovsdb.start()
        self.idl = self.ovsdb.idl

    def sync(self):
        self.idl.run()

    def get_chassis(self, name):
        try:
            chassis = idlutils.row_by_value(self.idl,
                                            'Chassis',
                                            'name', name)
            return OvsdbChassis(chassis)
        except idlutils.RowNotFound:
            return None

    def get_all_chassis(self):
        res = []
        for chassis in self.idl.tables['Chassis'].rows.values():
            res.append(OvsdbChassis(chassis))
        return res

    def add_chassis(self, name, ip, tunnel_type):
        txn = idl.Transaction(self.idl)

        encap_row = txn.insert(self.idl.tables['Encap'])
        encap_row.ip = ip
        encap_row.type = tunnel_type

        chassis_row = txn.insert(self.idl.tables['Chassis'])
        chassis_row.encaps = encap_row
        chassis_row.name = name
        status = txn.commit_block()
        return status

    def register_local_ports(self, chassis_name, local_ports_ids):
        txn = idl.Transaction(self.idl)

        chassis = idlutils.row_by_value(self.idl,
                                        'Chassis',
                                        'name', chassis_name)

        for binding in self.idl.tables['Binding'].rows.values():
            if binding.logical_port in local_ports_ids:
                if binding.chassis == chassis_name:
                    continue
                # Bind this port to this chassis
                binding.chassis = chassis
            elif binding.chassis == chassis_name:
                binding.chassis = []

        status = txn.commit_block()
        return status

    def get_all_logical_ports(self):
        res = []
        for binding in self.idl.tables['Binding'].rows.values():
            if not binding.chassis:
                continue
            port = {}
            port['id'] = binding.logical_port
            port['mac'] = binding.mac[0]
            port['chassis'] = binding.chassis[0].name
            port['network_id'] = str(binding.logical_datapath)
            port['tunnel_key'] = binding.tunnel_key
            res.append(port)
        return res


class OvsdbChassis(api_nb.Chassis):

    def __init__(self, row):
        self.chassis_row = row

    def get_name(self):
        return self.chassis_row.name

    def get_ip(self):
        encap = self.chassis_row.encaps[0]
        return encap.ip

    def get_encap_type(self):
        encap = self.chassis_row.encaps[0]
        return encap.type
