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

import functools

from neutron.agent.ovsdb import impl_idl
from neutron.agent.ovsdb.native import connection
from oslo_config import cfg
from ovs.db import idl

from dragonflow.common import constants
from dragonflow.ovsdb import commands
from dragonflow.ovsdb import objects

ovsdb_monitor_table_filter_default = {
    'Interface': [
        'ofport',
        'name',
        'admin_state',
        'type',
        'external_ids',
        'options',
        'mac_in_use',
        'ingress_policing_burst',
        'ingress_policing_rate',
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
        'qos',
    ],
    'QoS': [
        'queues',
        'external_ids',
        'type',
    ],
    'Queue': [
        'dscp',
        'external_ids',
        'other_config',
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


class DFIdl(idl.Idl):
    def __init__(self, nb_api, remote, schema):
        super(DFIdl, self).__init__(remote, schema)
        self.nb_api = nb_api
        self.interface_type = (constants.OVS_VM_INTERFACE,
                               constants.OVS_TUNNEL_INTERFACE,
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

    def notify(self, event, row, updates=None):
        if not row or not hasattr(row, '_table'):
            return
        if row._table.name == 'Interface':
            _interface = objects.LocalInterface.from_idl_row(row)
            action = event if event != 'update' else 'set'
            self._notify_update_local_interface(_interface, action)


class DFConnection(connection.Connection):
    """
    Extend the Neutron OVS Connection class to support being given the IDL
    schema externally or manually.
    Much of this code was taken directly from connection.Connection class.
    """
    def update_schema_helper(self, helper):
        tables = ovsdb_monitor_table_filter_default
        for table_name, columns in tables.items():
            if columns == 'all':
                helper.register_table(table_name)
            else:
                helper.register_columns(table_name, columns)


class DFOvsdbApi(impl_idl.OvsdbIdl):
    """The command generator of OVS DB operation

    This is a sub-class of OvsdbIdl, which is defined in neutron. The super
    class OvsdbIdl has defined lots of command. Dragonflow can use
    them. And Dragonflow can extend its own commands in this class.
    """
    ovsdb_connection = None

    def __init__(self, context, nb_api, db_connection, timeout):
        self.context = context
        if DFOvsdbApi.ovsdb_connection is None:
            DFOvsdbApi.ovsdb_connection = DFConnection(
                db_connection,
                timeout,
                'Open_vSwitch',
                idl_class=functools.partial(DFIdl, nb_api))
            # Override the super class's attribute
            impl_idl.OvsdbIdl.ovsdb_connection = DFOvsdbApi.ovsdb_connection

    def start(self):
        DFOvsdbApi.ovsdb_connection.start()
        self.idl = DFOvsdbApi.ovsdb_connection.idl

    def get_bridge_ports(self, bridge):
        return commands.GetBridgePorts(self, bridge)

    def add_patch_port(self, bridge, port, remote_name):
        return commands.AddPatchPort(self, bridge, port, remote_name)

    def add_virtual_tunnel_port(self, tunnel_type):
        return commands.AddVirtualTunnelPort(self, tunnel_type)

    def create_qos(self, port_id, qos):
        return commands.CreateQos(self, port_id, qos)

    def update_qos(self, port_id, qos):
        return commands.UpdateQos(self, port_id, qos)

    def delete_qos(self, port_id):
        return commands.DeleteQos(self, port_id)
