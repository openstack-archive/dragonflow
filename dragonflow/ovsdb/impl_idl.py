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
from dragonflow.db.models import switch
from dragonflow.ovsdb import commands

ovsdb_monitor_table_filter_default = {
    'Interface': [
        'port_num',
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

_HANDLED_INTERFACE_TYPES = (
    constants.SWITCH_COMPUTE_INTERFACE,
    constants.SWITCH_TUNNEL_INTERFACE,
    constants.SWITCH_BRIDGE_INTERFACE,
)


def _is_ovsport_update_valid(action, ovsport):
    if ovsport.name == cfg.CONF.df_metadata.metadata_interface:
        return True

    if ovsport.type not in _HANDLED_INTERFACE_TYPES:
        return False

    if ovsport.name.startswith('qg'):
        return False

    if (ovsport.type == constants.SWITCH_COMPUTE_INTERFACE and
            ovsport.lport is None):
        return False

    if action == 'set':
        # No need for 'updated' event if the port_num is being deleted
        ofport = ovsport.ofport
        if (ofport is None) or (ofport < 0):
            return False

    return True


def _get_interface_type(row):
    interface_type = row.type
    interface_name = row.name

    if interface_type == "internal" and "br" in interface_name:
        return constants.SWITCH_BRIDGE_INTERFACE

    if interface_type == "patch":
        return constants.SWITCH_PATCH_INTERFACE

    if 'iface-id' in row.external_ids:
        return constants.SWITCH_COMPUTE_INTERFACE

    options = row.options
    if 'remote_ip' in options:
        return constants.SWITCH_TUNNEL_INTERFACE

    return constants.SWITCH_UNKNOWN_INTERFACE


def _port_from_idl_row(row):
    res = switch.SwitchPort(
        id=str(row.uuid),
        name=row.name,
        type=_get_interface_type(row),
    )
    if row.ofport:
        res.port_num = int(row.ofport[0])

    if row.mac_in_use:
        res.mac_in_use = row.mac_in_use[0]

    if row.admin_state:
        res.admin_state = row.admin_state[0]

    if res.type == constants.SWITCH_PATCH_INTERFACE:
        res.peer = row.options['peer']

    if res.type == constants.SWITCH_TUNNEL_INTERFACE:
        res.tunnel_type = row.type

    external_ids = row.external_ids
    lport_id = external_ids.get('iface-id')
    if lport_id is not None:
        res.lport = lport_id

    attached_mac = external_ids.get('attached-mac')
    if attached_mac is not None:
        res.attached_mac = attached_mac

    return res


class DFIdl(idl.Idl):
    def __init__(self, remote, schema, db_change_callback):
        super(DFIdl, self).__init__(remote, schema)
        self.db_change_callback = db_change_callback

    def notify(self, event, row, updates=None):
        if not row or not hasattr(row, '_table'):
            return
        if row._table.name != 'Interface':
            return

        local_interface = _port_from_idl_row(row)
        action = event if event != 'update' else 'set'
        if _is_ovsport_update_valid(action, local_interface):
            self.db_change_callback(
                local_interface.table_name,
                local_interface.id,
                action,
                local_interface.to_json(),
            )


def df_idl_from_server(connection_string, schema_name,
                       db_change_callback):
    """Create the Idl instance by pulling the schema from OVSDB server"""
    helper = idlutils.get_schema_helper(connection_string, schema_name)
    tables = ovsdb_monitor_table_filter_default
    for table_name, columns in tables.items():
        if columns == 'all':
            helper.register_table(table_name)
        else:
            helper.register_columns(table_name, columns)
    return DFIdl(connection_string, helper, db_change_callback)


class DFOvsdbApi(impl_idl.OvsdbIdl):
    """The command generator of OVS DB operation

    This is a sub-class of OvsdbIdl, which is defined in neutron. The super
    class OvsdbIdl has defined lots of command. Dragonflow can use
    them. And Dragonflow can extend its own commands in this class.
    """
    def __init__(self, db_connection, timeout, db_change_callback):
        idl = df_idl_from_server(db_connection, 'Open_vSwitch',
                                 db_change_callback)
        type(self).ovsdb_connection = None
        ovsdb_connection = connection.Connection(idl, timeout)
        super(DFOvsdbApi, self).__init__(ovsdb_connection)

    def get_bridge_ports(self, bridge):
        return commands.GetBridgePorts(self, bridge)

    def add_patch_port(self, bridge, port, peer_port):
        return commands.AddPatchPort(self, bridge, port, peer_port)

    def add_virtual_tunnel_port(self, tunnel_type):
        return commands.AddVirtualTunnelPort(self, tunnel_type)

    def create_qos(self, port_id, qos):
        return commands.CreateQos(self, port_id, qos)

    def update_qos(self, port_id, qos):
        return commands.UpdateQos(self, port_id, qos)

    def delete_qos(self, port_id):
        return commands.DeleteQos(self, port_id)
