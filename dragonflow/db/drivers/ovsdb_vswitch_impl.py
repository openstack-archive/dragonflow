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

from neutron.agent.ovsdb import impl_idl
from neutron.agent.ovsdb.native import commands
from neutron.agent.ovsdb.native import connection
from neutron.agent.ovsdb.native import helpers
from neutron.agent.ovsdb.native import idlutils
from oslo_config import cfg
from ovs.db import idl
from ovs import poller
from ovs import vlog
import retrying
import six
import threading

from dragonflow.common import constants
from dragonflow.db import api_vswitch


ovsdb_monitor_table_filter_default = {
    'Interface': [
        'ofport',
        'name',
        'admin_state',
        'type',
        'external_ids',
        'options',
        'mac_in_use',
    ],
    'Bridge': [
        'ports',
        'name',
        'controller',
        'fail_mode',
        'datapath_type',
    ],
    'Port': [
        'name',
        'external_ids',
        'interfaces',
    ],
    'Controller': [
        'target',
    ],
    'Open_vSwitch': [
        'bridges',
        'cur_cfg',
        'next_cfg'
    ]
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


class DFOvsdbApi(impl_idl.OvsdbIdl):
    """The command generator of OVS DB operation

    This is a sub-class of OvsdbIdl, which is defined in neutron. The super
    class OvsdbIdl has defined lots of command. Dragonflow can use
    them. And Dragonflow can extend its own commands in this class.
    """
    ovsdb_connection = None

    def __init__(self, context, db_connection, timeout):
        self.context = context
        if DFOvsdbApi.ovsdb_connection is None:
            DFOvsdbApi.ovsdb_connection = DFConnection(
                db_connection,
                timeout,
                get_schema_helper(
                    db_connection,
                    tables=ovsdb_monitor_table_filter_default))
            # Override the super class's attribute
            impl_idl.OvsdbIdl.ovsdb_connection = DFOvsdbApi.ovsdb_connection

    def start(self):
        DFOvsdbApi.ovsdb_connection.start()
        self.idl = DFOvsdbApi.ovsdb_connection.idl

    def add_tunnel_port(self, chassis):
        return AddTunnelPort(self, chassis)

    def get_bridge_ports(self, bridge):
        return GetBridgePorts(self, bridge)

    def add_patch_port(self, bridge, port, remote_name):
        return AddPatchPort(self, bridge, port, remote_name)


class OvsdbSwitchApi(api_vswitch.SwitchApi):
    """The interface of openvswitch

    Consumers use this class to set openvswitch or get results from
    openvswitch.
    """

    def __init__(self, ip, nb_api,
                 protocol='tcp', port='6640', timeout=10):
        super(OvsdbSwitchApi, self).__init__()
        self.ip = ip
        self.protocol = protocol
        self.port = port
        # NOTE: This has to be this name vsctl_timeout, as neutron will use
        # this attribute to set the timeout of ovs db.
        self.vsctl_timeout = timeout
        self.ovsdb = None
        self.nb_api = nb_api
        self.ovsdb_monitor = None
        self.integration_bridge = cfg.CONF.df.integration_bridge
        vlog.Vlog.init('dragonflow')

    def initialize(self):
        db_connection = ('%s:%s:%s' % (self.protocol, self.ip, self.port))
        self.ovsdb = DFOvsdbApi(self, db_connection, self.vsctl_timeout)

        table = constants.OVS_INTERFACE
        self.nb_api.db_change_callback(table, None, 'sync_started', None)

        self.ovsdb.start()

        self.ovsdb_monitor = OvsdbMonitor(self.nb_api, self.ovsdb.idl)
        self.ovsdb_monitor.initialize()
        self.nb_api.db_change_callback(table, None, 'sync_finished', None)

    def db_get_val(self, table, record, column, check_error=False,
                   log_errors=True):
        return self.ovsdb.db_get(table, record, column).execute(
            check_error=check_error, log_errors=log_errors)

    def set_controller(self, bridge, targets):
        self.ovsdb.set_controller(bridge, targets).execute()

    def set_controller_fail_mode(self, bridge, fail_mode):
        self.ovsdb.set_fail_mode(bridge, fail_mode).execute()

    def check_controller(self, target):
        controllers = self.ovsdb.get_controller(
            self.integration_bridge).execute()
        return target in controllers

    def check_controller_fail_mode(self, fail_mode):
        return fail_mode == self.db_get_val('Bridge',
                                            self.integration_bridge,
                                            'fail_mode')

    def get_tunnel_ports(self):
        res = []
        ports = self.ovsdb.get_bridge_ports(self.integration_bridge).execute()
        for port in ports:
            if 'df-chassis-id' in port.external_ids:
                chassis_id = port.external_ids['df-chassis-id']
                res.append(OvsdbTunnelPort(port, chassis_id))
        return res

    def add_tunnel_port(self, chassis):
        self.ovsdb.add_tunnel_port(chassis).execute()

    def delete_port(self, switch_port):
        self.ovsdb.del_port(switch_port.get_name(),
                            self.integration_bridge).execute()

    def get_local_ports_to_ofport_mapping(self):
        lport_to_ofport = {}
        chassis_to_ofport = {}
        ports = self.ovsdb.get_bridge_ports(self.integration_bridge).execute()
        for port in ports:
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
        self.ovsdb.add_br(bridge, datapath_type='system').execute()
        if not self.patch_port_exist(port):
            self.ovsdb.add_patch_port(bridge, port, remote_name).execute()
        return self.get_port_ofport(port)

    def patch_port_exist(self, port):
        return 'patch' == self.db_get_val('Interface', port, 'type',
                                          check_error=False,
                                          log_errors=False)

    def get_port_ofport(self, port):
        return self.db_get_val('Interface', port, 'ofport',
                               check_error=False, log_errors=False)


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


class AddTunnelPort(commands.BaseCommand):
    def __init__(self, api, chassis):
        super(AddTunnelPort, self).__init__(api)
        self.chassis = chassis
        self.integration_bridge = cfg.CONF.df.integration_bridge

    def run_idl(self, txn):
        bridge = idlutils.row_by_value(self.api.idl, 'Bridge',
                                       'name', self.integration_bridge)
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


class GetBridgePorts(commands.BaseCommand):
    def __init__(self, api, bridge):
        super(GetBridgePorts, self).__init__(api)
        self.bridge = bridge

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        self.result = [p for p in br.ports if p.name != self.bridge]


class OvsdbMonitor(object):
    def __init__(self, nb_api, idl):
        super(OvsdbMonitor, self).__init__()
        self.nb_api = nb_api
        self.idl = idl
        self.interface_type = (constants.OVS_VM_INTERFACE,
                              constants.OVS_BRIDGE_INTERFACE)

    def _is_handle_interface_update(self, interface):
        if interface.name == cfg.CONF.df.metadata_interface:
            return True
        if interface.type not in self.interface_type:
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


class AddPatchPort(commands.BaseCommand):
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
