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

from dragonflow.db import api_vswitch

from ovs.db import idl

from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import idlutils


class OvsdbSwitchApi(api_vswitch.SwitchApi):

    def __init__(self, ip, protocol='tcp', port='6640', timeout=10):
        super(OvsdbSwitchApi, self).__init__()
        self.ip = ip
        self.db_name = 'Open_vSwitch'
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

    def get_tunnel_ports(self):
        res = []
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        for port in br_int.ports:
            if 'df-chassis-id' in port.external_ids:
                chassis_id = port.external_ids['df-chassis-id']
                res.append(OvsdbTunnelPort(port, chassis_id))
        return res

    def add_tunnel_port(self, chassis):
        bridge = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        txn = idl.Transaction(self.idl)
        port_name = "df-" + chassis.get_name()

        interface = txn.insert(self.idl.tables['Interface'])
        interface.name = port_name
        interface.type = chassis.get_encap_type()
        options_dict = getattr(interface, 'options', {})
        options_dict['remote_ip'] = chassis.get_ip()
        options_dict['key'] = 'flow'
        interface.options = options_dict

        port = txn.insert(self.idl.tables['Port'])
        port.name = port_name
        port.verify('interfaces')
        ifaces = getattr(port, 'interfaces', [])
        ifaces.append(interface)
        port.interfaces = ifaces
        external_ids_dict = getattr(interface, 'external_ids', {})
        external_ids_dict['df-chassis-id'] = chassis.get_name()
        port.external_ids = external_ids_dict

        bridge.verify('ports')
        ports = getattr(bridge, 'ports', [])
        ports.append(port)
        bridge.ports = ports

        status = txn.commit_block()
        return status

    def delete_port(self, switch_port):
        port = switch_port.port_row
        bridge = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        txn = idl.Transaction(self.idl)
        bridge.verify('ports')
        ports = bridge.ports
        ports.remove(port)
        bridge.ports = ports

        # Remote Port Interfaces
        port.verify('interfaces')
        for iface in port.interfaces:
            self.idl.tables['Interface'].rows[iface.uuid].delete()

        self.idl.tables['Port'].rows[port.uuid].delete()

        status = txn.commit_block()
        return status

    def get_local_port_ids(self):
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        port_ids = set()
        for port in br_int.ports:
            if port.name == 'br-int':
                continue
            if 'df-chassis-id' in port.external_ids:
                continue

            for interface in port.interfaces:
                if 'iface-id' in interface.external_ids:
                    port_ids.add(interface.external_ids['iface-id'])

        return port_ids

    def get_local_ports_to_ofport_mapping(self):
        lport_to_ofport = {}
        chassis_to_ofport = {}
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        for port in br_int.ports:
            if port.name == 'br-int':
                continue
            chassis_id = port.external_ids.get('df-chassis-id')
            for interface in port.interfaces:
                if interface.ofport is None:
                    # TODO(gsagie) log error
                    continue
                ofport = interface.ofport[0]
                if ofport < 1 or ofport > 65533:
                    # TODO(gsagie) log error
                    continue
                if chassis_id is not None:
                    chassis_to_ofport[chassis_id] = ofport
                else:
                    ifaceid = interface.external_ids.get('iface-id')
                    if ifaceid is not None:
                        lport_to_ofport[ifaceid] = ofport

        return chassis_to_ofport, lport_to_ofport


class OvsdbSwitchPort(api_vswitch.SwitchPort):

    def __init__(self, row):
        self.port_row = row

    def get_name(self):
        return self.port_row.name

    def get_id(self):
        pass


class OvsdbTunnelPort(OvsdbSwitchPort):

    def __init__(self, row, chassis_id):
        super(OvsdbTunnelPort, self).__init__(row)
        self.chassis_id = chassis_id

    def get_chassis_id(self):
        return self.chassis_id
