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

import collections
import fcntl
import os
import pytun
import scapy.all as scapy
import socket
import threading
import time

from dragonflow._i18n import _LI, _LW
from dragonflow.common.utils import DFDaemon
from dragonflow.tests.fullstack import test_objects as objects

from neutron.agent.common import utils

from oslo_log import log

LOG = log.getLogger(__name__)


# NOTE(oanson) This function also exists in nova. However, to save the time it
# takes to install nova in the tests, for this one lousy function, I copied it
# here.
def create_tap_dev(dev, mac_address=None):
    try:
        # First, try with 'ip'
        utils.execute(['ip', 'tuntap', 'add', dev, 'mode', 'tap'],
                      run_as_root=True, check_exit_code=[0, 2, 254])
    except Exception as e:
        print e
        # Second option: tunctl
        utils.execute(['tunctl', '-b', '-t', dev], run_as_root=True)
    if mac_address:
        utils.execute(['ip', 'link', 'set', dev, 'address', mac_address],
                      run_as_root=True, check_exit_code=[0, 2, 254])
    utils.execute(['ip', 'link', 'set', dev, 'up'], run_as_root=True,
                  check_exit_code=[0, 2, 254])


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
        self.tap = LogicalPortTap(self.port)

    def delete(self):
        self.tap.delete()
        self.port.delete()

    @property
    def name(self):
        return self.port.get_logical_port().get_id()


class LogicalPortTap(object):
    def __init__(self, port):
        # NOTE(oanson) port is Port above. and port.port is PortTestWrapper.
        self.port = port
        self.lport = self.port.get_logical_port()
        self.tap = self._create_tap_device()
        self.fileno = self.tap.fileno()
        self.is_blocking = True

    def _create_tap_device(self):
        flags = pytun.IFF_TAP | pytun.IFF_NO_PI
        name = self._get_tap_interface_name()
        create_tap_dev(name, self.lport.get_mac())
        tap = pytun.TunTapDevice(flags=flags, name=name)
        self._connect_tap_device_to_vswitch('br-int', tap.name)
        tap.up()
        return tap

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
        LOG.info(_LI('Closing tap interface {} ({})').format(
            self.tap.name,
            self.tap.fileno(),
        ))
        self.tap.close()

    def _packet_raw_data_to_hex(self, buf):
        return buf.encode('hex')
        #return ''.join(['{:02x}'.format(ord(octet)) for octet in buf])

    def send(self, buf):
        LOG.info(_LI('send: via {}: {}').format(
            self.tap.name,
            self._packet_raw_data_to_hex(buf)))
        return self.tap.write(buf)

    def read(self):
        # NOTE(oanson) May block if no data is ready (i.e. no packet in buffer)
        if self.is_blocking:
            buf = self.tap.read(self.tap.mtu)
        else:
            fd = self.tap.fileno()
            if self.fileno != fd:
                LOG.warning(_LW('Warning: Fileno has changed: {}->{}').format(
                    self.fileno,
                    fd,
                ))
            buf = os.read(fd, self.tap.mtu)
        LOG.info(_LI('receive: via {}: {}').format(
            self.tap.name,
            self._packet_raw_data_to_hex(buf)))
        return buf

    def set_blocking(self, is_blocking):
        tap = self.tap
        fd = tap.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        if is_blocking:
            flags |= os.O_NONBLOCK
        else:
            flags &= ~os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.is_blocking = is_blocking


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


class Policy(object):
    def __init__(self, initial_actions, port_policies, unknown_port_action):
        self.initial_actions = initial_actions
        self.port_policies = port_policies
        self.unknown_port_action = unknown_port_action
        self.threads = []
        self.topology = None  # Set on start
        self.exceptions = collections.deque()

    def handle_packet(self, port_thread, buf):
        port = port_thread.port
        port_id = port.port_id
        subnet = port.subnet
        subnet_id = subnet.subnet_id
        try:
            port_policy = self.port_policies[(subnet_id, port_id)]
            try:
                port_policy.handle_packet(self, port_thread, buf)
            except Exception as e:
                self.add_exception(e)
        except KeyError:
            try:
                self.unknown_port_action(self, None, port_thread, buf)
            except Exception as e:
                self.add_exception(e)

    def start(self, topology):
        if self.topology:
            raise Exception('Policy already started')
        self.topology = topology
        # Start a thread for each port, listening on the LogicalPortTap
        for subnet in topology.subnets:
            for port in subnet.ports:
                thread = PortThread(self.handle_packet, port)
                thread.start()
                self.threads.append(thread)
        # Call the initial_actions
        for action in self.initial_actions:
            action(self, None, None, None)

    def wait(self, timeout=None):
        if timeout is not None:
            entry_time = time.time()
        for thread in self.threads:
            thread.wait(timeout)
            if timeout is not None:
                timeout -= time.time() - entry_time
                if timeout <= 0:
                    raise Exception('Timeout')

    def stop(self):
        for thread in self.threads:
            thread.stop()
        self.topology = None

    def add_exception(self, exception):
        self.exceptions.append(exception)
        self.stop()


class PortPolicy(object):
    def __init__(self, rules, default_action):
        self.rules = rules
        self.default_action = default_action

    def handle_packet(self, policy, port_thread, buf):
        for rule in self.rules:
            if rule.apply_rule(policy, port_thread, buf):
                return
        self.default_action(policy, None, port_thread, buf)


class PortPolicyRule(object):
    def __init__(self, packet_filter, actions):
        self.packet_filter = packet_filter
        self.actions = actions
        self.packet_filter = packet_filter
        self.disabled = False

    def match_packet(self, buf):
        """
        Check if this rule matches the packet (provided as a raw string in buf)
        """
        return self.packet_filter(buf)

    def apply_rule(self, policy, port_thread, buf):
        """
        Check if this rule matches the packet (provided as a raw string in buf)
        If it does, execute the actions.
        """
        if self.disabled:
            return False
        if not self.match_packet(buf):
            return False
        for action in self.actions:
            action(policy, self, port_thread, buf)
        return True


class Filter(object):
    def __call__(self, buf):
        raise Exception('Filter not implemented')


class ScapyIPv6Filter(object):
    def __call__(self, buf):
        pkt = scapy.Ether(buf)
        if pkt[0].type != 0x86dd:  # IPv6 protocol
            return False
        return True


class ScapyARPReplyFilter(object):
    def __call__(self, buf):
        pkt = scapy.Ether(buf)
        if pkt[0].type != 0x806:  # ARP protocol
            return False
        if pkt[1].op != 2:  # ARP reply
            return False
        return True


class Action(object):
    def __call__(self, policy, rule, port_thread, buf):
        raise Exception('Action not implemented')


class LogAction(Action):
    def __call__(self, policy, rule, port_thread, buf):
        pkt = scapy.Ether(buf)
        LOG.info(_LI('LogAction: Got packet: {}').format(pkt.summary()))


class SendAction(Action):
    def __init__(self, subnet_id, port_id, packet):
        self.subnet_id = subnet_id
        self.port_id = port_id
        self.packet = packet

    def __call__(self, policy, rule, port_thread, buf):
        interface_object = self._get_interface_object(policy.topology)
        packet = self.packet
        if not isinstance(packet, str):
            # TODO(oanson) pass more info to the packet generator
            packet = packet(buf)
        interface_object.send(packet)

    def _get_interface_object(self, topology):
        subnet = topology.subnets[self.subnet_id]
        port = subnet.ports[self.port_id]
        return port.tap


class RaiseAction(Action):
    def __init__(self, message):
        self.message = message

    def __call__(self, policy, rule, port_thread, buf):
        pkt = scapy.Ether(buf)
        raise Exception("Packet raised exception: {}".format(pkt.summary()))


class DisableRuleAction(Action):
    def __call__(self, policy, rule, port_thread, buf):
        rule.disabled = True


class StopThreadAction(Action):
    def __call__(self, policy, rule, port_thread, buf):
        port_thread.stop()


class StopSimulationAction(Action):
    def __call__(self, policy, rule, port_thread, buf):
        policy.stop()


class IgnoreAction(Action):
    def __call__(self, policy, rule, port_thread, buf):
        pass


class PortThread(object):
    def __init__(self, packet_handler, port):
        self.packet_handler = packet_handler
        self.port = port
        self.daemon = DFDaemon(is_not_light=True)
        self.is_working = False
        self.thread_id = None

    def start(self):
        self.is_working = True
        self.daemon.daemonize(self.run)

    def stop(self):
        self.is_working = False
        if self.thread_id != threading.current_thread().ident:
            self.daemon.stop()

    def wait(self, timeout=None):
        self.daemon.wait(timeout)

    def run(self):
        self.thread_id = threading.current_thread().ident
        tap = self.port.tap
        tap.set_blocking(False)
        while self.is_working:
            try:
                buf = tap.read()
                self.packet_handler(self, buf)
            except Exception as e:
                LOG.info(_LI('Reading from {}/{} failed: {}').format(
                    tap.tap.name,
                    self.port.name,
                    e))
                break
        try:
            tap.set_blocking(True)
        except Exception as e:
            pass  # ignore - reset blocking as best effort only
        self.stop()
