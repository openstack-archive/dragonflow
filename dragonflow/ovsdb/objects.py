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


class OvsdbPort(object):

    def __init__(self, name):
        super(OvsdbPort, self).__init__()
        self.name = name

    def get_name(self):
        return self.name


class OvsdbVirtuaTunnelPort(OvsdbPort):

    def __init__(self, name, tunnel_type):
        super(OvsdbVirtuaTunnelPort, self).__init__(name)
        self.tunnel_type = tunnel_type

    def get_tunnel_type(self):
        return self.tunnel_type


class OvsdbQos(object):

    def __init__(self, qos_id, version):
        super(OvsdbQos, self).__init__()
        self.qos_id = qos_id
        self.version = int(version)

    def get_qos_id(self):
        return self.qos_id

    def get_version(self):
        return self.version
