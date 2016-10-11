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

from dragonflow.common import constants


class LocalInterface(object):

    def __init__(self):
        super(LocalInterface, self).__init__()
        self.uuid = ""
        self.ofport = None
        self.name = ""
        self.admin_state = ""
        self.type = ""
        self.iface_id = ""
        self.peer = ""
        self.attached_mac = ""
        self.mac_in_use = ""
        self.remote_ip = ""
        self.remote_chassis_id = ""
        self.tunnel_type = ""

    @classmethod
    def _get_interface_type(cls, row):
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

    @classmethod
    def from_idl_row(cls, row):
        result = cls()
        result.uuid = row.uuid
        if row.ofport:
            result.ofport = int(row.ofport[0])
        if row.mac_in_use:
            result.mac_in_use = row.mac_in_use[0]
        result.name = row.name
        if row.admin_state:
            result.admin_state = row.admin_state[0]
        result.type = cls._get_interface_type(row)
        external_ids = row.external_ids
        result.iface_id = external_ids.get('iface-id', "")
        result.attached_mac = external_ids.get('attached-mac', "")
        if result.type == "patch":
            result.peer = row.options['peer']
        if result.type == "tunnel":
            result.remote_ip = row.options['remote_ip']
            result.remote_chassis_id = external_ids.get("df-chassis-id", "")
            result.tunnel_type = row.type
        return result

    def get_id(self):
        return self.uuid

    def get_ofport(self):
        return self.ofport

    def get_name(self):
        return self.name

    def get_admin_state(self):
        return self.admin_state

    def get_type(self):
        return self.type

    def get_iface_id(self):
        return self.iface_id

    def get_peer(self):
        return self.peer

    def get_attached_mac(self):
        return self.attached_mac

    def get_mac_in_use(self):
        return self.mac_in_use

    def get_remote_ip(self):
        return self.remote_ip
		
    def get_remote_chassis(self):
        return self.remote_chassis_id

    def get_tunnel_type(self):
        return self.tunnel_type

    def __str__(self):
        if self.ofport is None:
            self.ofport = -1
        return ("uuid:%s, ofport:%d, name:%s, "
                "admin_state:%s, type:%s, "
                "iface_id:%s, peer:%s, "
                "attached_mac:%s, mac_in_use:%s, remote_ip:%s, "
                "tunnel_type:%s, remote_chassis_id:%s" % (self.uuid,
                    self.ofport,
                    self.name,
                    self.admin_state,
                    self.type,
                    self.iface_id,
                    self.peer,
                    self.attached_mac,
                    self.mac_in_use,
                    self.remote_ip,
                    self.tunnel_type,
                    self.remote_chassis_id))


class OvsdbTunnelPort(object):

    def __init__(self, name, chassis_id):
        super(OvsdbTunnelPort, self).__init__()
        self.name = name
        self.chassis_id = chassis_id

    def get_chassis_id(self):
        return self.chassis_id

    def get_name(self):
        return self.name
