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


class SwitchApi(object):

    def sync(self):
        pass

    def set_controllers(self, bridge, targets):
        pass

    def del_controller(self, bridge):
        pass

    def get_tunnel_ports(self):
        pass

    def add_tunnel_port(self, chassis):
        pass

    def delete_port(self, switch_port):
        pass

    def get_logical_ports_to_ofport(self):
        pass

    def get_chassis_ids_to_ofport(self):
        pass

    def get_local_port_ids(self):
        pass


class SwitchPort(object):

    def get_name(self):
        pass

    def get_id(self):
        pass


class TunnelPort(SwitchPort):

    def get_chassis_id(self):
        pass


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
        self.remote_ip = ""
        self.tunnel_type = ""

    def __str__(self):

        return "uuid:%s, ofport:%d, name:%s, " \
               "admin_state:%s, type:%s, " \
               "iface_id:%s, peer:%s, " \
               "attached_mac:%s, remote_ip:%s, " \
               "tunnel_type:%s" % (self.uuid,
                    self.ofport,
                    self.name,
                    self.admin_state,
                    self.type,
                    self.iface_id,
                    self.peer,
                    self.attached_mac,
                    self.remote_ip,
                    self.tunnel_type)
