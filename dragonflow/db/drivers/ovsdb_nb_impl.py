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

import netaddr

from dragonflow.db import api_nb

from ovs.db import idl

from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import idlutils


class OvsdbNbApi(api_nb.NbApi):

    def __init__(self, ip, protocol='tcp', port='6640', timeout=10):
        super(OvsdbNbApi, self).__init__()
        self.ip = ip
        self.protocol = protocol
        self.port = port
        self.timeout = timeout
        self.ovsdb = None
        self.ovsdb_nb = None
        self.idl = None
        self.idl_nb = None

    def initialize(self):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))
        self.ovsdb = connection.Connection(db_connection,
                                           self.timeout,
                                           'OVN_Southbound')
        self.ovsdb_nb = connection.Connection(db_connection,
                                              self.timeout,
                                              'OVN_Northbound')
        self.ovsdb.start()
        self.ovsdb_nb.start()
        self.idl = self.ovsdb.idl
        self.idl_nb = self.ovsdb_nb.idl

    def sync(self):
        self.idl.run()
        self.idl_nb.run()

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
            res.append(OvsdbLogicalPort(binding, self.idl_nb))
        return res

    def get_routers(self):
        res = []
        for router in self.idl_nb.tables['Logical_Router'].rows.values():
            res.append(OvsdbLogicalRouter(router, self.idl_nb))
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


class OvsdbLogicalPort(api_nb.LogicalPort):

    def __init__(self, row, idl_nb):
        self.id = row.logical_port
        self.mac = row.mac[0]
        self.chassis = row.chassis[0].name
        self.network_id = str(row.logical_datapath)
        self.tunnel_key = row.tunnel_key
        self.external_dict = {}
        self.idl_nb = idl_nb
        self.lport = idlutils.row_by_value(self.idl_nb,
                                           'Logical_Port',
                                           'name', self.id)
        ips = getattr(self.lport, 'ips', [])
        self.ip = ips[0]

    def get_id(self):
        return self.id

    def get_mac(self):
        return self.mac

    def get_ip(self):
        return self.ip

    def get_chassis(self):
        return self.chassis

    def get_lswitch_id(self):
        return self.network_id

    def get_tunnel_key(self):
        return self.tunnel_key

    def set_external_value(self, key, value):
        self.external_dict[key] = value

    def get_external_value(self, key):
        return self.external_dict.get(key)


class OvsdbLogicalRouter(api_nb.LogicalRouter):

    def __init__(self, row, idl_nb):
        self.row = row
        self.idl_nb = idl_nb
        self.name = row.name
        lrouter_ports = getattr(self.row, 'ports', [])
        self.ports = []
        for port in lrouter_ports:
            port = OvsdbLogicalRouterPort(port, self.idl_nb)
            self.ports.append(port)

    def get_name(self):
        return self.name

    def get_ports(self):
        return self.ports


class OvsdbLogicalRouterPort(api_nb.LogicalRouterPort):

    def __init__(self, row, idl_nb):
        self.row = row
        self.idl_nb = idl_nb
        self.name = row.name
        self.mac = row.mac
        self.network = row.network
        self.cidr = netaddr.IPNetwork(row.network)
        for lswitch in self.idl_nb.tables['Logical_Switch'].rows.values():
            rport = getattr(lswitch, 'router_port', None)
            if rport is not None and rport != []:
                if rport[0] == self.row:
                    self.network_id = str(lswitch.uuid)

    def get_name(self):
        return self.name

    def get_ip(self):
        return str(self.cidr.ip)

    def get_cidr_network(self):
        return str(self.cidr.network)

    def get_cidr_netmask(self):
        return str(self.cidr.netmask)

    def get_mac(self):
        return self.mac

    def get_lswitch_id(self):
        return self.network_id

    def get_network(self):
        return self.network

    def __eq__(self, other):
        return self.name == other.get_name()
