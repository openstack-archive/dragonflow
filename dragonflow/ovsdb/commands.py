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
from oslo_log import log

from dragonflow._i18n import _LE, _LI

LOG = log.getLogger(__name__)


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


class DelAllQos(commands.BaseCommand):
    def __init__(self, api, version):
        super(DelAllQos, self).__init__(api)
        self.version = version

    def _delete_rows_by_version(self, table_name):
        rows = self.api.idl.tables[table_name].rows
        delete_rows = []
        for row in six.itervalues(rows):
            external_dict = row.external_ids
            version = external_dict.get('version')
            if not version or version == str(self.version):
                delete_rows.append(row)
        for row in delete_rows:
            row.delete()

    def run_idl(self, txn):
        self._delete_rows_by_version('QoS')
        self._delete_rows_by_version('Queue')


class AddPortQos(commands.BaseCommand):
    def __init__(self, api, port_id, qos, version):
        super(AddPortQos, self).__init__(api)
        self.port_id = port_id
        self.qos = qos
        self.version = version

    def run_idl(self, txn):
        max_kbps = self.qos.get_max_kbps()
        max_burst_kbps = self.qos.get_max_burst_kbps()
        if not max_kbps or not max_burst_kbps:
            return

        wanted_interface = None
        interfaces = self.api.idl.tables['Interface'].rows
        for interface in six.itervalues(interfaces):
            external_dict = interface.external_ids
            iface_id = external_dict.get('iface-id')
            if iface_id == self.port_id and interface.type != 'patch':
                wanted_interface = interface
                break
        if not wanted_interface:
            LOG.error(_LE("Could not get interface "
                          "for qos by lport_id:%s"), self.port_id)
            return

        wanted_interface.verify('ingress_policing_rate')
        wanted_interface.ingress_policing_rate = max_kbps
        wanted_interface.verify('ingress_policing_burst')
        wanted_interface.ingress_policing_burst = max_burst_kbps

        port_name = wanted_interface.name
        ovs_port = idlutils.row_by_value(self.api.idl, 'Port',
                                         'name', port_name)
        ovs_port.verify('qos')
        qos = txn.insert(self.api.idl.tables['QoS'])
        qos.type = 'linux-htb'
        qos_external_ids = {}
        qos_external_ids['version'] = str(self.version)
        qos_external_ids['iface-id'] = self.port_id
        qos.external_ids = qos_external_ids
        ovs_port.qos = qos.uuid

        queue = txn.insert(self.api.idl.tables['Queue'])
        dscp = self.qos.get_dscp_marking()
        if dscp is None:
            LOG.info(_LI("The dscp is None"))
        else:
            queue.dscp = dscp
        queue_external_ids = {}
        queue_external_ids['version'] = str(self.version)
        queue_external_ids['iface-id'] = self.port_id
        queue.external_ids = queue_external_ids
        queue.verify('other_config')
        other_config = getattr(queue, 'other_config', {})
        max_bps = max_kbps * 1024
        other_config['max-rate'] = str(max_bps)
        other_config['min-rate'] = str(max_bps)
        queue.other_config = other_config

        qos.verify('queues')
        qos.queues = {0: queue.uuid}


class DelPortQos(commands.BaseCommand):
    def __init__(self, api, port_id):
        super(DelPortQos, self).__init__(api)
        self.port_id = port_id

    def run_idl(self, txn):
        wanted_interface = None
        interfaces = self.api.idl.tables['Interface'].rows
        for interface in six.itervalues(interfaces):
            external_dict = interface.external_ids
            iface_id = external_dict.get('iface-id')
            if iface_id == self.port_id and interface.type != 'patch':
                wanted_interface = interface
                break
        if not wanted_interface:
            LOG.error(_LE("Could not get interface "
                          "for qos by lport_id:%s"), self.port_id)
            return

        wanted_interface.verify('ingress_policing_rate')
        wanted_interface.ingress_policing_rate = 0
        wanted_interface.verify('ingress_policing_burst')
        wanted_interface.ingress_policing_burst = 0

        port_name = wanted_interface.name
        ovs_port = idlutils.row_by_value(self.api.idl, 'Port',
                                         'name', port_name)
        qos = getattr(ovs_port, 'qos', [])
        ovs_port.verify('qos')
        ovs_port.qos = []
        if len(qos) > 0:
            qos_id = qos[0].uuid
            queues = qos[0].queues
            if queues and len(queues) > 0:
                queue_id = queues[0].uuid
                self.api.idl.tables['Queue'].rows[queue_id].delete()
            self.api.idl.tables['QoS'].rows[qos_id].delete()


class DelQosAndQueue(commands.BaseCommand):
    def __init__(self, api, port_id):
        super(DelQosAndQueue, self).__init__(api)
        self.port_id = port_id

    def _delete_rows_by_port_id(self, table_name):
        rows = self.api.idl.tables[table_name].rows
        delete_rows = []
        for row in six.itervalues(rows):
            external_dict = row.external_ids
            iface_id = external_dict.get('iface-id')
            if not iface_id or iface_id == self.port_id:
                delete_rows.append(row)
        for row in delete_rows:
            row.delete()

    def run_idl(self, txn):
        self._delete_rows_by_port_id('QoS')
        self._delete_rows_by_port_id('Queue')
