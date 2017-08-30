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
from jsonmodels import fields

from dragonflow.common import constants
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import l2
from dragonflow.db.models import mixins


def _get_interface_type(row):
    interface_type = row.type
    interface_name = row.name

    if interface_type == "internal" and "br" in interface_name:
        return constants.OVS_BRIDGE_INTERFACE

    if interface_type == "patch":
        return constants.OVS_PATCH_INTERFACE

    if 'iface-id' in row.external_ids:
        return constants.OVS_VM_INTERFACE

    options = row.options
    if 'remote_ip' in options:
        return constants.OVS_TUNNEL_INTERFACE

    return constants.OVS_UNKNOWN_INTERFACE


@mf.register_model
@mf.construct_nb_db_model
class OvsPort(mf.ModelBase, mixins.BasicEvents, mixins.Name):
    table_name = 'ovs_port'

    ofport = fields.IntField()
    admin_state = df_fields.EnumField(('up', 'down'))
    lport = df_fields.ReferenceField(l2.LogicalPort)
    type = df_fields.EnumField(
        (
            constants.OVS_BRIDGE_INTERFACE,
            constants.OVS_PATCH_INTERFACE,
            constants.OVS_VM_INTERFACE,
            constants.OVS_TUNNEL_INTERFACE,
            constants.OVS_UNKNOWN_INTERFACE,
        ),
    )
    peer = fields.StringField()
    peer_bridge = fields.StringField()
    mac_in_use = df_fields.MacAddressField()
    attached_mac = df_fields.MacAddressField()
    tunnel_type = fields.StringField()

    @classmethod
    def from_idl_row(cls, row):
        res = cls(
            id=str(row.uuid),
            name=row.name,
            type=_get_interface_type(row),
        )
        if row.ofport:
            res.ofport = int(row.ofport[0])

        if row.mac_in_use:
            res.mac_in_use = row.mac_in_use[0]

        if row.admin_state:
            res.admin_state = row.admin_state[0]

        if res.type == constants.OVS_PATCH_INTERFACE:
            res.peer = row.options['peer']
            res.peer_bridge = row.external_ids['peer_bridge']

        if res.type == constants.OVS_TUNNEL_INTERFACE:
            res.tunnel_type = row.type

        external_ids = row.external_ids
        lport_id = external_ids.get('iface-id')
        if lport_id is not None:
            res.lport = lport_id

        attached_mac = external_ids.get('attached-mac')
        if attached_mac is not None:
            res.attached_mac = attached_mac

        return res
