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

from neutron.agent.ovsdb import impl_idl
from neutron.agent.ovsdb.native import commands
from neutron.agent.ovsdb.native.commands import BaseCommand
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

    def transaction(self, check_error=False, log_errors=True, **kwargs):
        return impl_idl.Transaction(self,
                                    self.ovsdb,
                                    self.timeout,
                                    check_error, log_errors)

    def sync(self):
        self.idl.run()

    def del_controller(self, bridge):
        return DelControllerCommand(self, bridge)

    def set_controllers(self, bridge, targets):
        return SetControllerCommand(self, bridge, targets)

    def get_tunnel_ports(self):
        res = []
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')

        for port in br_int.ports:
            if 'df-chassis-id' in port.external_ids:
                chassis_id = port.external_ids['df-chassis-id']
                res.append(OvsdbTunnelPort(port, chassis_id))
        return res

    def add_tunnel_port(self, chassis):
        return AddTunnelPort(self, chassis)

    def delete_port(self, switch_port):
        return DeleteSwitchPort(self, switch_port)

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

    def get_local_port_id_from_name(self, name):
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        for port in br_int.ports:
            if port.name != name:
                continue
            for interface in port.interfaces:
                if 'iface-id' in interface.external_ids:
                    return interface.external_ids['iface-id']

        return None

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

    def create_patch_port(self, bridge, port, remote_name):
        if not commands.BridgeExistsCommand(self, bridge).execute():
            commands.AddBridgeCommand(self, bridge, True,
                                      datapath_type='system').execute()
            AddPatchPort(self, bridge, port, remote_name).execute()
        else:
            if not self.patch_port_exist(port):
                AddPatchPort(self, bridge, port, remote_name).execute()
        return self.get_patch_port_ofport(port)

    def delete_patch_port(self, bridge, port):
        if not commands.BridgeExistsCommand(self, bridge).execute():
            return
        else:
            commands.DelPortCommand(self, port, bridge,
                                    if_exists=True).execute()

    def patch_port_exist(self, port):
        cmd = commands.DbGetCommand(self, 'Interface', port, 'type')
        return bool('patch' == cmd.execute(check_error=False,
                    log_errors=False))

    def get_patch_port_ofport(self, port):
        cmd = commands.DbGetCommand(self, 'Interface', port, 'ofport')
        return cmd.execute(check_error=False, log_errors=False)


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


class DelControllerCommand(BaseCommand):
    def __init__(self, api, bridge):
        super(DelControllerCommand, self).__init__(api)
        self.bridge = bridge

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        br.controller = []


class SetControllerCommand(BaseCommand):
    def __init__(self, api, bridge, targets):
        super(SetControllerCommand, self).__init__(api)
        self.bridge = bridge
        self.targets = targets

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        controllers = []
        for target in self.targets:
            controller = txn.insert(self.api.idl.tables['Controller'])
            controller.target = target
            controllers.append(controller)
        br.verify('controller')
        br.controller = controllers


class DeleteSwitchPort(BaseCommand):
    def __init__(self, api, switch_port):
        super(DeleteSwitchPort, self).__init__(api)
        self.switch_port = switch_port

    def run_idl(self, txn):
        port = self.switch_port.port_row
        bridge = idlutils.row_by_value(self.api.idl, 'Bridge',
                                       'name', 'br-int')
        bridge.verify('ports')
        ports = bridge.ports
        ports.remove(port)
        bridge.ports = ports

        # Remote Port Interfaces
        port.verify('interfaces')
        for iface in port.interfaces:
            self.api.idl.tables['Interface'].rows[iface.uuid].delete()

        self.api.idl.tables['Port'].rows[port.uuid].delete()


class AddTunnelPort(BaseCommand):
    def __init__(self, api, chassis):
        super(AddTunnelPort, self).__init__(api)
        self.chassis = chassis

    def run_idl(self, txn):
        bridge = idlutils.row_by_value(self.api.idl, 'Bridge',
                                       'name', 'br-int')
        port_name = "df-" + self.chassis.get_name()

        interface = txn.insert(self.api.idl.tables['Interface'])
        interface.name = port_name
        interface.type = self.chassis.get_encap_type()
        options_dict = getattr(interface, 'options', {})
        options_dict['remote_ip'] = self.chassis.get_ip()
        options_dict['key'] = 'flow'
        interface.options = options_dict

        port = txn.insert(self.api.idl.tables['Port'])
        port.name = port_name
        port.verify('interfaces')
        ifaces = getattr(port, 'interfaces', [])
        ifaces.append(interface)
        port.interfaces = ifaces
        external_ids_dict = getattr(interface, 'external_ids', {})
        external_ids_dict['df-chassis-id'] = self.chassis.get_name()
        port.external_ids = external_ids_dict

        bridge.verify('ports')
        ports = getattr(bridge, 'ports', [])
        ports.append(port)
        bridge.ports = ports


class AddPatchPort(BaseCommand):
    def __init__(self, api, bridge, port, remote_name):
        super(AddPatchPort, self).__init__(api)
        self.bridge = bridge
        self.port = port
        self.remote_name = remote_name

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        port = txn.insert(self.api.idl.tables['Port'])
        port.name = self.port
        br.verify('ports')
        ports = getattr(br, 'ports', [])
        ports.append(port)
        br.ports = ports

        iface = txn.insert(self.api.idl.tables['Interface'])
        iface.name = self.port
        port.verify('interfaces')
        ifaces = getattr(port, 'interfaces', [])
        options_dict = getattr(iface, 'options', {})
        options_dict['peer'] = self.remote_name
        iface.options = options_dict
        iface.type = 'patch'
        ifaces.append(iface)
        port.interfaces = ifaces
