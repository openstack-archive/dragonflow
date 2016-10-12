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

from neutron.agent.ovsdb.native import commands
from neutron.agent.ovsdb.native import idlutils
from oslo_config import cfg


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


class GetBridgePorts(commands.BaseCommand):
    def __init__(self, api, bridge):
        super(GetBridgePorts, self).__init__(api)
        self.bridge = bridge

    def run_idl(self, txn):
        br = idlutils.row_by_value(self.api.idl, 'Bridge', 'name', self.bridge)
        self.result = [p for p in br.ports if p.name != self.bridge]


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


class AddVirtualTunnelPort(commands.BaseCommand):
    def __init__(self, api, tunnel_type):
        super(AddVirtualTunnelPort, self).__init__(api)
        self.tunnel_type = tunnel_type
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.port = tunnel_type + "-vtp"

    def run_idl(self, txn):
        port = idlutils.row_by_value(self.api.idl, 'Port', 'name',
                                     self.port, None)
        if port:
            return

        bridge = idlutils.row_by_value(self.api.idl, 'Bridge',
                                       'name', self.integration_bridge)

        port = txn.insert(self.api._tables['Port'])
        port.name = self.port
        bridge.verify('ports')
        ports = getattr(bridge, 'ports', [])
        ports.append(port)
        bridge.ports = ports

        iface = txn.insert(self.api._tables['Interface'])
        txn.expected_ifaces.add(iface.uuid)
        iface.name = self.port
        iface.type = self.tunnel_type
        options_dict = getattr(iface, 'options', {})
        options_dict['remote_ip'] = 'flow'
        options_dict['key'] = 'flow'
        options_dict['local_ip'] = cfg.CONF.df.local_ip
        iface.options = options_dict
        port.verify('interfaces')
        ifaces = getattr(port, 'interfaces', [])
        ifaces.append(iface)
        port.interfaces = ifaces
