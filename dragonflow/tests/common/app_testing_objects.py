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

import pytun
import socket

from dragonflow._i18n import _LI
from dragonflow.tests.fullstack import test_objects as objects

from neutron.agent.common import utils

from oslo_log import log

LOG = log.getLogger(__name__)


class Topology(object):
    def __init__(self, neutron, nb_api):
        """
        Create a network. That's our playing field
        """
        self.neutron = neutron
        self.nb_api = nb_api
        self.network = objects.NetworkTestWrapper(neutron, nb_api)
        self.subnets = []
        self.routers = []
        self.network.create()

    def delete(self):
        for router in self.routers:
            router.delete()
        self.routers = []
        for subnet in self.subnets:
            subnet.delete()
        self.subnets = []
        if self.network.network_id:
            self.network.delete()

    def create_subnet(self, cidr='192.168.0.0/24'):
        subnet_id = len(self.subnets)
        subnet = Subnet(self, subnet_id, cidr)
        self.subnets.append(subnet)
        return subnet

    def create_router(self, subnet_ids):
        router_id = len(self.routers)
        router = Router(self, router_id, subnet_ids)
        self.routers.append(router)
        return router


class Subnet(object):
    def __init__(self, topology, subnet_id, cidr):
        self.topology = topology
        self.subnet_id = subnet_id
        self.ports = []
        self.subnet = objects.SubnetTestWrapper(
            self.topology.neutron,
            self.topology.nb_api,
            self.topology.network.network_id
        )
        self.subnet.create(subnet={
            'cidr': cidr,
            'ip_version': 4,
            'network_id': topology.network.network_id
        })

    def delete(self):
        for port in self.ports:
            port.delete()
        self.ports = []
        self.subnet.delete()

    def create_port(self):
        port_id = len(self.ports)
        port = Port(self, port_id)
        self.ports.append(port)
        return port


class Port(object):
    def __init__(self, subnet, port_id):
        self.subnet = subnet
        self.port_id = port_id
        network_id = self.subnet.topology.network.network_id
        self.port = objects.PortTestWrapper(
            self.subnet.topology.neutron,
            self.subnet.topology.nb_api,
            network_id,
        )
        self.port.create({
            'admin_state_up': True,
            'fixed_ips': [{
                'subnet_id': self.subnet.subnet.subnet_id,
            }],
            'network_id': network_id,
            'binding:host_id': socket.gethostname(),
        })
        self.tap = LogicalPortTap(self.port.get_logical_port())

    def delete(self):
        self.tap.delete()
        self.port.delete()


class LogicalPortTap(object):
    def __init__(self, lport):
        self.lport = lport
        self.tap = self._create_tap_device()

    def _create_tap_device(self):
        flags = pytun.IFF_TAP | pytun.IFF_NO_PI
        name = self._get_tap_interface_name()
        tap = pytun.TunTapDevice(flags=flags, name=name)
        tap.hwaddr = self._get_mac_as_raw()
        self._connect_tap_device_to_vswitch('br-int', tap.name)
        tap.up()
        return tap

    def _get_mac_as_raw(self):
        """
        mac is of the form 'xx:xx:xx:xx:xx:xx'
        Should be \\xxx\\xxx\\xxx\\xxx\\xxx\\xxx
        """
        mac = self.lport.get_mac()
        return mac.replace(':', '').decode('hex')

    def _get_tap_interface_name(self):
        lport_name = self.lport.get_id()
        lport_name_prefix = lport_name[:11]
        return 'tap{}'.format(lport_name_prefix)

    def _connect_tap_device_to_vswitch(self, vswitch_name, tap_name):
        full_args = ['ovs-vsctl', 'add-port', vswitch_name, tap_name]
        utils.execute(full_args, run_as_root=True, process_input=None)

    def _disconnect_tap_device_to_vswitch(self, vswitch_name, tap_name):
        full_args = ['ovs-vsctl', 'del-port', vswitch_name, tap_name]
        utils.execute(full_args, run_as_root=True, process_input=None)

    def delete(self):
        self._disconnect_tap_device_to_vswitch('br-int', self.tap.name)
        self.tap.close()

    def _packet_raw_data_to_hex(self, buf):
        return ''.join(['{:02x}'.format(ord(octet)) for octet in buf])

    def send(self, buf):
        LOG.info(_LI('send: via {}: {}').format(
            self.tap.name,
            self._packet_raw_data_to_hex(buf)))
        return self.tap.write(buf)

    def read(self):
        # NOTE(oanson) May block if no data is ready (i.e. no packet in buffer)
        buf = self.tap.read(self.tap.mtu)
        LOG.info(_LI('receive: via {}: {}').format(
            self.tap.name,
            self._packet_raw_data_to_hex(buf)))
        return buf


class Router(object):
    def __init__(self, topology, router_id, subnet_ids):
        self.topology = topology
        self.router_id = router_id
        self.subnet_ids = subnet_ids
        self.router = objects.RouterTestWrapper(
            self.topology.neutron,
            self.topology.nb_api,
        )
        self.router.create(router={
            'admin_state_up': True
        })
        for subnet_id in self.subnet_ids:
            subnet = self.topology.subnets[subnet_id]
            subnet_uuid = subnet.subnet.subnet_id
            self.router.add_interface(subnet_id=subnet_uuid)

    def delete(self):
        self.router.delete()


class TAPInterface(object):
    pass


class Policy(object):
    pass


class PortPolicy(object):
    pass


class PortPolicyRule(object):
    pass


class SendAction(object):
    pass


class RaiseAction(object):
    pass


class DisableRuleAction(object):
    pass
