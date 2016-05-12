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

import retrying
import six
import threading

from dragonflow.common import constants
from dragonflow.db import api_vswitch

from neutron.agent.ovsdb import impl_idl
from neutron.agent.ovsdb.native import commands
from neutron.agent.ovsdb.native.commands import BaseCommand
from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import helpers
from neutron.agent.ovsdb.native import idlutils

from oslo_log import log

from ovs.db import idl
from ovs import poller


LOG = log.getLogger(__name__)


ovsdb_monitor_table_filter_default = {
    'Interface': [
        'ofport',
        'name',
        'admin_state',
        'type',
        'external_ids',
        'options',
    ],
    'Bridge': [
        'ports',
        'name',
        'controller',
        'fail_mode',
    ],
    'Port': [
        'name',
        'external_ids',
        'interfaces',
    ],
    'Controller': [
        'target',
    ],
}


def get_schema_helper(connection_string, db_name='Open_vSwitch', tables='all'):
    try:
        helper = idlutils.get_schema_helper(connection_string,
                                            db_name)
    except Exception:
        # We may have failed do to set-manager not being called
        helpers.enable_connection_uri(connection_string)

        # There is a small window for a race, so retry up to a second
        @retrying.retry(wait_exponential_multiplier=10,
                        stop_max_delay=1000)
        def do_get_schema_helper():
            return idlutils.get_schema_helper(connection_string,
                                              db_name)
        helper = do_get_schema_helper()
    if tables == 'all':
        helper.register_all()
    elif isinstance(tables, dict):
        for table_name, columns in six.iteritems(tables):
            if columns == 'all':
                helper.register_table(table_name)
            else:
                helper.register_columns(table_name, columns)
    return helper


class DFConnection(connection.Connection):
    """
    Extend the Neutron OVS Connection class to support being given the IDL
    schema externally or manually.
    Much of this code was taken directly from connection.Connection class.
    """
    def __init__(
            self, connection, timeout, schema_helper):
        super(DFConnection, self).__init__(connection, timeout, None)
        assert schema_helper is not None, "schema_helper parameter is None"
        self._schema_helper = schema_helper

    def start(self):
        with self.lock:
            if self.idl is not None:
                return

            self.idl = idl.Idl(self.connection, self._schema_helper)
            idlutils.wait_for_change(self.idl, self.timeout)
            self.poller = poller.Poller()
            self.thread = threading.Thread(target=self.run)
            self.thread.setDaemon(True)
            self.thread.start()


class OvsdbSwitchApi(api_vswitch.SwitchApi):

    def __init__(self, ip, nb_api,
                 protocol='tcp', port='6640', timeout=10):
        super(OvsdbSwitchApi, self).__init__()
        self.ip = ip
        self.protocol = protocol
        self.port = port
        self.timeout = timeout
        self.ovsdb = None
        self.idl = None
        self.nb_api = nb_api
        self.ovsdb_monitor = None

    def initialize(self):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))
        self.ovsdb = DFConnection(
            db_connection,
            self.timeout,
            get_schema_helper(
                db_connection,
                tables=ovsdb_monitor_table_filter_default
            ),
        )
        table = constants.OVS_INTERFACE
        self.nb_api.db_change_callback(table, None, 'sync_started', None)

        self.ovsdb.start()
        self.idl = self.ovsdb.idl

        self.ovsdb_monitor = OvsdbMonitor(self.nb_api, self.idl)
        self.ovsdb_monitor.initialize()
        self.nb_api.db_change_callback(table, None, 'sync_finished', None)

    @property
    def _tables(self):
        return self.idl.tables

    @property
    def _ovs(self):
        return list(self._tables['Open_vSwitch'].rows.values())[0]

    def transaction(self, check_error=False, log_errors=True, **kwargs):
        return impl_idl.Transaction(self,
                                    self.ovsdb,
                                    self.timeout,
                                    check_error, log_errors)

    def del_controller(self, bridge):
        return DelControllerCommand(self, bridge)

    def set_controllers(self, bridge, targets):
        return SetControllerCommand(self, bridge, targets)

    def set_controller_fail_mode(self, bridge, fail_mode):
        return SetControllerFailModeCommand(self, bridge, fail_mode)

    def check_controller(self, target):
        is_controller_set = False
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        # if controller is not set, len(controller) is 0
        if br_int is not None and (
           len(br_int.controller) > 0 and
           br_int.controller[0].target == target):
            is_controller_set = True
        return is_controller_set

    def check_controller_fail_mode(self, fail_mode):
        is_fail_mode_set = False
        br_int = idlutils.row_by_value(self.idl, 'Bridge', 'name', 'br-int')
        # if fail_mode is not set, len(fail_mode) is 0
        if br_int is not None and (
           len(br_int.fail_mode) > 0 and
           br_int.fail_mode[0] == fail_mode):
            is_fail_mode_set = True
        return is_fail_mode_set

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
        if commands.BridgeExistsCommand(self, bridge).execute():
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


class SetControllerFailModeCommand(BaseCommand):
    def __init__(self, api, bridge, fail_mode):
        super(SetControllerFailModeCommand, self).__init__(api)
        self.bridge = bridge
        self.fail_mode = fail_mode

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        br.verify('fail_mode')
        br.fail_mode = [self.fail_mode]


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
        port_name = "df-" + self.chassis.get_id()

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
        external_ids_dict['df-chassis-id'] = self.chassis.get_id()
        port.external_ids = external_ids_dict

        bridge.verify('ports')
        ports = getattr(bridge, 'ports', [])
        ports.append(port)
        bridge.ports = ports


class OvsdbMonitor(object):
    def __init__(self, nb_api, idl):
        super(OvsdbMonitor, self).__init__()
        self.nb_api = nb_api
        self.idl = idl

    def _is_handle_interface_update(self, interface):
        if interface.type != constants.OVS_VM_INTERFACE:
            return False
        if interface.name.startswith('qg'):
            return False
        return True

    def _notify_update_local_interface(self, local_interface, action):
        if self._is_handle_interface_update(local_interface):
            table = constants.OVS_INTERFACE
            key = local_interface.uuid
            self.nb_api.db_change_callback(table, key, action, local_interface)

    def _notify_existing_interfaces(self):
        interfaces = self.idl.tables['Interface']
        for row in six.itervalues(interfaces.rows):
            self.notify('create', row)

    def initialize(self):
        self.idl.notify = self.notify
        self._notify_existing_interfaces()

    def notify(self, event, row, updates=None):
        if not row or not hasattr(row, '_table'):
            return
        if row._table.name == 'Interface':
            _interface = api_vswitch.LocalInterface.from_idl_row(row)
            action = event if event != 'update' else 'set'
            self._notify_update_local_interface(_interface, action)


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
