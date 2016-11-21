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

import six

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


class CreateQos(commands.BaseCommand):
    def __init__(self, api, port_id, qos):
        super(CreateQos, self).__init__(api)
        self.port_id = port_id
        self.qos = qos

    def run_idl(self, txn):
        queue = txn.insert(self.api.idl.tables['Queue'])
        dscp = self.qos.get_dscp_marking()
        if dscp:
            queue.dscp = dscp

        queue_external_ids = {}
        queue_external_ids['iface-id'] = self.port_id
        queue.external_ids = queue_external_ids
        queue.verify('other_config')
        other_config = getattr(queue, 'other_config', {})
        max_kbps = self.qos.get_max_kbps()
        max_bps = max_kbps * 1024
        other_config['max-rate'] = str(max_bps)
        other_config['min-rate'] = str(max_bps)
        queue.other_config = other_config

        qos = txn.insert(self.api.idl.tables['QoS'])
        qos.type = 'linux-htb'
        qos_external_ids = {}
        qos_external_ids['version'] = str(self.qos.get_version())
        qos_external_ids['qos-id'] = self.qos.get_id()
        qos_external_ids['iface-id'] = self.port_id
        qos.external_ids = qos_external_ids
        qos.verify('queues')
        qos.queues = {0: queue.uuid}

        self.result = qos.uuid


class DeleteQos(commands.BaseCommand):
    def __init__(self, api, port_id):
        super(DeleteQos, self).__init__(api)
        self.port_id = port_id

    def run_idl(self, txn):
        conditions = [('external_ids', '=', {'iface-id': self.port_id})]
        rows_to_delete = []
        for table in ['QoS', 'Queue']:
            for r in six.itervalues(self.api._tables[table].rows):
                if idlutils.row_match(r, conditions):
                    rows_to_delete.append(r)

        for r in rows_to_delete:
            r.delete()


class UpdateQos(commands.BaseCommand):
    def __init__(self, api, port_id, qos):
        super(UpdateQos, self).__init__(api)
        self.port_id = port_id
        self.qos = qos

    def run_idl(self, txn):
        conditions = [('external_ids', '=', {'iface-id': self.port_id})]
        queue_table = self.api._tables['Queue']
        for r in six.itervalues(queue_table.rows):
            if idlutils.row_match(r, conditions):
                dscp = self.qos.get_dscp_marking()
                dscp = dscp if dscp else []
                setattr(r, 'dscp', dscp)

                max_kbps = self.qos.get_max_kbps()
                max_bps = max_kbps * 1024 if max_kbps else 0
                other_config = getattr(r, 'other_config', {})
                other_config['max-rate'] = str(max_bps)
                other_config['min-rate'] = str(max_bps)
                setattr(r, 'other_config', other_config)

        qos_table = self.api._tables['QoS']
        for r in six.itervalues(qos_table.rows):
            if idlutils.row_match(r, conditions):
                external_ids = getattr(r, 'external_ids', {})
                external_ids['version'] = str(self.qos.get_version())
                external_ids['qos-id'] = self.qos.get_id()
                setattr(r, 'external_ids', external_ids)
