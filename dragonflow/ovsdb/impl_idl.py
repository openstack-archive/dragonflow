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

from oslo_config import cfg
from ovs.db import idl
from ovsdbapp.backend.ovs_idl import connection
from ovsdbapp.backend.ovs_idl import idlutils
from ovsdbapp.schema.open_vswitch import impl_idl


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
        if interface.name == cfg.CONF.df_metadata.metadata_interface:
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


def df_idl_from_server(nb_api, connection_string, schema_name):
    """Create the Idl instance by pulling the schema from OVSDB server"""
    helper = idlutils.get_schema_helper(connection_string, schema_name)
    tables = ovsdb_monitor_table_filter_default
    for table_name, columns in tables.items():
        if columns == 'all':
            helper.register_table(table_name)
        else:
            helper.register_columns(table_name, columns)
    return DFIdl(nb_api, connection_string, helper)


class DFOvsdbApi(impl_idl.OvsdbIdl):
    """The command generator of OVS DB operation

    This is a sub-class of OvsdbIdl, which is defined in neutron. The super
    class OvsdbIdl has defined lots of command. Dragonflow can use
    them. And Dragonflow can extend its own commands in this class.
    """
    ovsdb_connection = None

    def __init__(self, nb_api, db_connection, timeout):
        if DFOvsdbApi.ovsdb_connection is None:
            idl = df_idl_from_server(nb_api, db_connection, 'Open_vSwitch')
            DFOvsdbApi.ovsdb_connection = connection.Connection(idl, timeout)

        super(DFOvsdbApi, self).__init__(DFOvsdbApi.ovsdb_connection)

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
