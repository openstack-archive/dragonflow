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
import netaddr
import os
import re
import socket
import threading
import time

from neutron.agent.common import utils
from oslo_log import log
import pytun
from ryu.lib.packet import arp
from ryu.lib.packet import dhcp
from ryu.lib.packet import icmp
from ryu.lib.packet import icmpv6
from ryu.lib.packet import ipv4
from ryu.lib.packet import ipv6
from ryu.lib.packet import packet

from dragonflow._i18n import _LI, _LE
from dragonflow.common import utils as d_utils
from dragonflow import conf as cfg
from dragonflow.tests.common import utils as test_utils
from dragonflow.tests.fullstack import test_objects as objects


LOG = log.getLogger(__name__)


# NOTE(oanson) This function also exists in nova. However, to save the time it
# takes to install nova in the tests, for this one function, I copied it here.
def create_tap_dev(dev, mac_address=None):
    """Create a tap with name dev and MAC address mac_address on the
    operating system.
    :param dev:         The name of the tap device to create
    :type dev:          String
    :param mac_address: The MAC address of the device, format xx:xx:xx:xx:xx:xx
    :type mac_address:  String
    """
    try:
        # First, try with 'ip'
        utils.execute(['ip', 'tuntap', 'add', dev, 'mode', 'tap'],
                      run_as_root=True, check_exit_code=[0, 2, 254])
    except Exception:
        try:
            # Second option: tunctl
            utils.execute(['tunctl', '-b', '-t', dev], run_as_root=True)
        except Exception:
            LOG.exception('Error while creating tap device {0}'.format(dev))
            raise

    if mac_address:
        utils.execute(['ip', 'link', 'set', dev, 'address', mac_address],
                      run_as_root=True, check_exit_code=[0, 2, 254])
    utils.execute(['ip', 'link', 'set', dev, 'up'], run_as_root=True,
                  check_exit_code=[0, 2, 254])


def delete_tap_device(dev):
    """Delete a tap with name dev on the operating system.
    :param dev: The name of the tap device to delete
    :type dev:  String
    """
    try:
        # First, try with 'ip'
        utils.execute(['ip', 'tuntap', 'del', 'dev', dev, 'mode', 'tap'],
                      run_as_root=True, check_exit_code=[0, 2, 254])
    except Exception:
        try:
            # Second option: tunctl
            utils.execute(['tunctl', '-d', dev], run_as_root=True)
        except Exception:
            LOG.exception('Error while deleting tap device {0}'.format(dev))
            raise


def packet_raw_data_to_hex(buf):
    return str(buf).encode('hex')


class Topology(object):
    """Create and contain all the topology information. This includes routers,
    subnets, and ports.
    """
    def __init__(self, neutron, nb_api):
        """Create a network. That's our playing field."""
        self._is_closed = False
        self.neutron = neutron
        self.nb_api = nb_api
        self.network = objects.NetworkTestObj(neutron, nb_api)
        self.external_network = objects.ExternalNetworkTestObj(neutron, nb_api)
        self.exist_external_net = False
        self.subnets = []
        self.routers = []
        self.network.create()
        # Because it's hard to get the default security group in this
        # context, we create a fake one here to act like the default security
        # group when creating a port with no security group specified.
        self.fake_default_security_group = \
            self._create_fake_default_security_group()

    def _create_fake_default_security_group(self):
        security_group = objects.SecGroupTestObj(self.neutron, self.nb_api)
        security_group_id = security_group.create(
            secgroup={'name': 'fakedefault'})

        ingress_rule_info = {'ethertype': 'IPv4',
                             'direction': 'ingress',
                             'remote_group_id': security_group_id}
        security_group.rule_create(secrule=ingress_rule_info)

        return security_group

    def delete(self):
        """Delete this topology. Also deletes all contained routers, subnets
        and ports.
        """
        for router in self.routers:
            router.delete()
        self.routers = []
        for subnet in self.subnets:
            subnet.delete()
        self.subnets = []
        self.network.close()
        if not self.exist_external_net:
            self.external_network.close()
        self.fake_default_security_group.close()

    def close(self):
        if not self._is_closed:
            self._is_closed = True
            self.delete()

    def create_subnet(self, cidr=None, enable_dhcp=True):
        """Create a subnet in this topology, with the given subnet address
        range.
        :param cidr: The subnet's address range, in form <IP>/<mask len>.
                     If it is None, the cidr will be allocated from default
                     subnetpool.
        :type cidr:  String
        :param enable_dhcp: Whether to enable dhcp for this subnet.
        :type cidr:  Boolean
        """
        subnet_id = len(self.subnets)
        subnet = Subnet(self, subnet_id, cidr, enable_dhcp)
        self.subnets.append(subnet)
        return subnet

    def create_router(self, subnet_ids):
        """Create a router in this topology, connected to the given subnets.
        :param subnet_ids: List of subnet ids to which the router is connected
        :type subnet_ids:  List
        """
        router_id = len(self.routers)
        router = Router(self, router_id, subnet_ids)
        self.routers.append(router)
        return router

    def create_external_network(self, router_ids):
        """Create external network in this topology, and use it as external
        gateway to given routers.
        """
        external_net = objects.find_first_network(self.neutron,
                                                  {'router:external': True})
        if external_net:
            self.exist_external_net = True
            external_net_id = external_net['id']
        else:
            external_net_id = self.external_network.create()

        for r in router_ids:
            router = self.routers[r]
            router.router.set_gateway(external_net_id)

        return external_net_id


class Subnet(object):
    """Represent a single subnet."""
    def __init__(self, topology, subnet_id, cidr, enable_dhcp):
        """Create the subnet under the given topology, with the given ID, and
        the given address range.
        :param topology:  The topology to which the subnet belongs
        :type topology:   Topology
        :param subnet_id: The subnet's ID in the topology. Created by topology
        :type subnet_id:  Number (Opaque)
        :param cidr:      The address range for this subnet. Format IP/MaskLen.
                          If it is None, the cidr will be allocated from
                          default subnetpool.
        :type cidr:       String
        :param enable_dhcp: Whether to enable dhcp for this subnet.
        :type cidr:  Boolean
        """
        self.topology = topology
        self.subnet_id = subnet_id
        self.ports = []
        self.subnet = objects.SubnetTestObj(
            self.topology.neutron,
            self.topology.nb_api,
            self.topology.network.network_id
        )
        if cidr:
            ip_version = self._get_ip_version(cidr)
            self.subnet.create(subnet={
                'cidr': cidr,
                'enable_dhcp': enable_dhcp,
                'ip_version': ip_version,
                'network_id': topology.network.network_id
            })
        else:
            self.subnet.create()

    def update(self, updated_parameters):
        self.subnet.update(updated_parameters)

    def delete(self):
        """Delete this subnet, and all attached ports."""
        for port in self.ports:
            port.delete()
        self.ports = []
        self.subnet.close()

    def create_port(self, security_groups=None):
        """Create a port attached to this subnet.
        :param security_groups:  The security groups that this port is
        associating with
        """
        port_id = len(self.ports)
        security_groups_used = security_groups
        if security_groups_used is None:
            security_groups_used = \
                [self.topology.fake_default_security_group.secgroup_id]
        port = Port(self,
                    port_id=port_id,
                    security_groups=security_groups_used)
        self.ports.append(port)
        return port

    def _get_ip_version(self, cidr):
        """
        Calculates the IP version from the CIDR, and returns it.
        Raises AddrFormatError if the CIDR is not correctly formatted
        :param cidr: The address range for this subnet. Format IP/MaskLen
        """
        network = netaddr.IPNetwork(cidr)
        ip_version = network.ip.version
        return ip_version


class Port(object):
    """Represent a single port. Also contains access to the underlying tap
    device
    """
    def __init__(self, subnet, port_id, security_groups=None):
        """Create a single port in the given subnet, with the given port_id
        :param subnet:  The subnet on which this port is created
        :type subnet:   Subnet
        :param port_id: The ID of this port. Created internally by subnet
        :type port_id:  Number (Opaque)
        """
        self.subnet = subnet
        self.port_id = port_id
        network_id = self.subnet.topology.network.network_id
        self.port = objects.PortTestObj(
            self.subnet.topology.neutron,
            self.subnet.topology.nb_api,
            network_id,
        )
        parameters = {
            'admin_state_up': True,
            'fixed_ips': [{
                'subnet_id': self.subnet.subnet.subnet_id,
            }],
            'network_id': network_id,
            'binding:host_id': socket.gethostname(),
        }
        if security_groups is not None:
            parameters["security_groups"] = security_groups
        self.port.create(parameters)
        self.tap = LogicalPortTap(self.port)

    def update(self, updated_parameters):
        self.port.update(updated_parameters)

    def delete(self):
        """Delete this port. Delete the underlying tap device."""
        self.tap.delete()
        self.port.close()

    @property
    def name(self):
        """Return the name of this port, i.e. the name of the underlying tap
        device.
        """
        return self.port.get_logical_port().get_id()


class LogicalPortTap(object):
    """Represent a tap device on the operating system."""
    def __init__(self, port):
        """Create a tap device represented by the given port.
        :param port: The configuration info of this tap device
        :type port:  Port
        """
        self.port = port
        self.integration_bridge = cfg.CONF.df.integration_bridge
        self.lport = self.port.get_logical_port()
        self.tap = self._create_tap_device()
        self.is_blocking = True

    def _create_tap_device(self):
        flags = pytun.IFF_TAP | pytun.IFF_NO_PI
        name = self._get_tap_interface_name()
        create_tap_dev(name, self.lport.get_mac())
        tap = pytun.TunTapDevice(flags=flags, name=name)
        self._connect_tap_device_to_vswitch(self.integration_bridge, tap.name)
        tap.up()
        return tap

    def _get_tap_interface_name(self):
        lport_name = self.lport.get_id()
        lport_name_prefix = lport_name[:11]
        return 'tap{}'.format(lport_name_prefix)

    def _connect_tap_device_to_vswitch(self, vswitch_name, tap_name):
        """Connect the tap device to the given vswitch, and add it to the
        ovsdb.
        :param vswitch_name: The name of the vswitch to connect the device
        :type vswitch_name:  String
        :param tap_name:     The name of the device to connect
        :type tap_name:      String
        """
        full_args = ['ovs-vsctl', 'add-port', vswitch_name, tap_name]
        utils.execute(full_args, run_as_root=True, process_input=None)
        full_args = ['ovs-vsctl', 'set', 'interface', tap_name,
                     'external_ids:iface-id={}'.format(self.lport.get_id())]
        utils.execute(full_args, run_as_root=True, process_input=None)

    def _disconnect_tap_device_to_vswitch(self, vswitch_name, tap_name):
        full_args = ['ovs-vsctl', 'del-port', vswitch_name, tap_name]
        utils.execute(full_args, run_as_root=True, process_input=None)

    def delete(self):
        self._disconnect_tap_device_to_vswitch(self.integration_bridge,
                                               self.tap.name)
        LOG.info(_LI('Closing tap interface {} ({})').format(
            self.tap.name,
            self.tap.fileno(),
        ))
        self.tap.close()
        delete_tap_device(self.tap.name)

    def send(self, buf):
        """Send a packet out via the tap device.
        :param buf: Raw packet data to send
        :type buf:  String (decoded)
        """
        LOG.info(_LI('send: via {}: {}').format(
            self.tap.name,
            packet_raw_data_to_hex(buf)))
        if self.is_blocking:
            return self.tap.write(buf)
        else:
            fd = self.tap.fileno()
            return os.write(fd, buf)

    def read(self):
        """Read data from the tap device. This method may block if no data is
        ready (i.e. no packet in buffer).
        Return the read buffer, which is a String (encoded).
        """
        if self.is_blocking:
            buf = self.tap.read(self.tap.mtu)
        else:
            fd = self.tap.fileno()
            buf = os.read(fd, self.tap.mtu)
        LOG.info(_LI('receive: via {}: {}').format(
            self.tap.name,
            packet_raw_data_to_hex(buf)))
        return buf

    def set_blocking(self, is_blocking):
        """Set the device to be blocking or non-blocking.
        :param is_blocking: Set the blocking state to is_blocking
        :type is_blocking:  Boolean
        """
        tap = self.tap
        fd = tap.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        if not is_blocking:
            flags |= os.O_NONBLOCK
        else:
            flags &= ~os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        self.is_blocking = is_blocking


class Router(object):
    """Represent a router in the topology."""
    def __init__(self, topology, router_id, subnet_ids):
        """Create a router in the topology. Add router interfaces for each
        subnet.
        :param topology:   The topology to which the router belongs
        :type topology:    Topology
        :param router_id:  The ID of the router. Created in Topology.
        :type router_id:   Number (opaque)
        :param subnet_ids: List of subnets to which the router is connected
        :type subnet_ids:  List
        """
        self.topology = topology
        self.router_id = router_id
        self.subnet_ids = subnet_ids
        self.router = objects.RouterTestObj(
            self.topology.neutron,
            self.topology.nb_api,
        )
        self.router.create(router={
            'admin_state_up': True
        })
        self.router_interfaces = {}
        for subnet_id in self.subnet_ids:
            subnet = self.topology.subnets[subnet_id]
            subnet_uuid = subnet.subnet.subnet_id
            router_interface = self.router.add_interface(subnet_id=subnet_uuid)
            self.router_interfaces[subnet_id] = router_interface

    def delete(self):
        """Delete this router."""
        self.router.close()


class TimeoutException(Exception):

    def __init__(self):
        super(TimeoutException, self).__init__('Timeout')


class Policy(object):
    """Represent a policy, i.e. the expected packets on each port in the
    topology, and the actions to take in each case.
    """
    def __init__(self, initial_actions, port_policies, unknown_port_action):
        """Create a policy.
        :param initial_actions:     Take these actions when policy is started
        :type initial_actions:      List of Action
        :param port_policies:       The policy for each port in the topology
        :type port_policies:        dict (subnet_id, port_id) -> PortPolicy
        :param unknown_port_action: Take this action for packets on ports not
                in port_policies
        :type unknown_port_action:  Action
        """
        self.initial_actions = initial_actions
        self.port_policies = port_policies
        self.unknown_port_action = unknown_port_action
        self.threads = []
        self.topology = None  # Set on start
        self.exceptions = collections.deque()

    def handle_packet(self, port_thread, buf):
        """Event handler for a packet received on a port. Test the received
        packet against the policy.
        :param port_thread: Receiving port
        :type port_thread:  PortThread
        :param buf:         Packet data
        :type buf:          String (encoded)
        """
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
        """Start the policy on the given topology. Start threads listening on
        the ports. Execute the initial actions.
        :param topology: The topology on which to run the policy
        :type topology:  Topology
        """
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
        """Wait for all the threads listening on devices to finish. Threads are
        generally stopped via actions, and this command waits for the
        simulation to end.
        :param timeout: After this many seconds, throw an exception
        :type timeout:  Number
        """
        exception = TimeoutException()
        if timeout is not None:
            entry_time = time.time()
        for thread in self.threads:
            thread.wait(timeout, exception)
            if timeout is not None:
                timeout -= time.time() - entry_time
                if timeout <= 0:
                    raise exception

    def stop(self):
        """Stop all threads. Prepare for a new simulation."""
        for thread in self.threads:
            thread.stop()
        self.topology = None

    def close(self):
        if self.topology:
            self.stop()

    def add_exception(self, exception):
        """Exception handler. Record this exception to be read later by the
        caller
        :param exception: The exception to record
        :type exception:  Exception
        """

        LOG.exception(_LE('Adding exception:'))
        self.exceptions.append(exception)
        self.stop()


class PortPolicy(object):
    """A policy for a specific port. The rules to apply for an incoming packet,
    and the relevant actions to take
    """
    def __init__(self, rules, default_action):
        """Create a policy for a port.
        :param rules:          The rules against which to test incoming packets
        :type rules:           List of PortPolicyRule
        :param default_action: The action to take for a packet not matching any
                rules.
        :type default_action:  Action
        """
        self.rules = rules
        self.default_action = default_action

    def handle_packet(self, policy, port_thread, buf):
        """Packet handler. Run the packet through the rules. Apply the relevant
        actions.
        :param port_thread: Receiving port
        :type port_thread:  PortThread
        :param buf:         Packet data
        :type buf:          String (encoded)
        """
        for rule in self.rules:
            if rule.apply_rule(policy, port_thread, buf):
                return
        self.default_action(policy, None, port_thread, buf)


class PortPolicyRule(object):
    """Represent a single policy rule. i.e. packet match parameters, and the
    actions to take if the packet matches.
    """
    def __init__(self, packet_filter, actions):
        """Create the rule.
        :param packet_filter: The packet match parametrer
        :type packet_filter:  Filter
        :param actions:       The actions to take if the packet matches
        :type actions:        List of Action
        """
        self.packet_filter = packet_filter
        self.actions = actions
        self.disabled = False

    def match_packet(self, buf):
        """Check if the given packet matches this rule
        :param buf: Raw packet data to send
        :type buf:  String (decoded)
        """
        return self.packet_filter(buf)

    def apply_rule(self, policy, port_thread, buf):
        """Check if the given packet matches this rule, and execute the
        relevant actions if it does.
        :param policy:      The currently running policy
        :type policy:       Policy
        :param port_thread: Receiving port
        :type port_thread:  PortThread
        :param buf:         Raw packet data to send
        :type buf:          String (decoded)
        """
        if self.disabled:
            return False
        if not self.match_packet(buf):
            return False
        for action in self.actions:
            action(policy, self, port_thread, buf)
        return True


class Filter(object):
    """Base class of packet filters, i.e. match parameters."""
    def __call__(self, buf):
        """Test if the packet matches this filter. Return True if it does, and
        False otherwise.
        :param buf: Packet data
        :type buf:  String (encoded)
        """
        raise Exception('Filter not implemented')


class RyuIPv6Filter(object):
    """Use ryu to parse the packet and test if it's IPv6."""
    def __call__(self, buf):
        pkt = packet.Packet(buf)
        return (pkt.get_protocol(ipv6.ipv6) is not None)


class RyuFilterIcmpv6ProtocolType(object):
    """
    Use ryu to parse the object and see if it from the requested icmpv6 type
    """
    type_ = icmpv6.icmpv6

    def __call__(self, buf):
        pkt = packet.Packet(buf)
        pkt_protocol = pkt.get_protocol(icmpv6.icmpv6)
        if not pkt_protocol:
            return False
        return pkt_protocol.type_ == self.type_


class RyuNeighborAdvertisementFilter(RyuFilterIcmpv6ProtocolType):
    """Use ryu to parse the packet and test if it's a Neighbor Advertisement"""
    type_ = icmpv6.ND_NEIGHBOR_ADVERT


class RyuIpv6MulticastFilter(RyuFilterIcmpv6ProtocolType):
    """Use ryu to parse the object and see if it is a multicast request"""
    type_ = icmpv6.MLDV2_LISTENER_REPORT


class RyuARPRequestFilter(object):
    """Use ryu to parse the packet and test if it's an ARP request."""
    def __init__(self, arp_tpa=None):
        self.arp_tpa = arp_tpa

    def __call__(self, buf):
        pkt = packet.Packet(buf)
        pkt_arp_protocol = pkt.get_protocol(arp.arp)
        if (not pkt_arp_protocol) or (
                    pkt_arp_protocol.opcode != arp.ARP_REQUEST):
            return False
        if self.arp_tpa is not None:
            return pkt_arp_protocol.dst_ip == self.arp_tpa

        return True


class RyuARPReplyFilter(object):
    """Use ryu to parse the packet and test if it's an ARP reply."""
    def __call__(self, buf):
        pkt = packet.Packet(buf)
        pkt_arp_protocol = pkt.get_protocol(arp.arp)
        if not pkt_arp_protocol:
            return False
        return pkt_arp_protocol.opcode == 2


class RyuARPGratuitousFilter(object):
    """Use ryu to parse the packet and test if it's a gratuitous ARP."""
    def __call__(self, buf):
        pkt = packet.Packet(buf)
        pkt_arp_protocol = pkt.get_protocol(arp.arp)
        if not pkt_arp_protocol:
            return False
        return pkt_arp_protocol.src_ip == pkt_arp_protocol.dst_ip


# Taken from the DHCP app
def _get_dhcp_message_type_opt(dhcp_packet):
    for opt in dhcp_packet.options.option_list:
        if opt.tag == dhcp.DHCP_MESSAGE_TYPE_OPT:
            return ord(opt.value)


class RyuDHCPFilter(object):
    """Use ryu to parse the packet and test if it's a DHCP Ack"""
    def __call__(self, buf):
        pkt = packet.Packet(buf)
        return (pkt.get_protocol(dhcp.dhcp) is not None)


class RyuDHCPPacketTypeFilter(object):
    """Use ryu to parse the packet and test if it's a DHCP Ack"""
    def __call__(self, buf):
        pkt = packet.Packet(buf)
        pkt_dhcp_protocol = pkt.get_protocol(dhcp.dhcp)
        if not pkt_dhcp_protocol:
            return False
        dhcp_type = _get_dhcp_message_type_opt(pkt_dhcp_protocol)
        return dhcp_type == self.get_dhcp_packet_type()

    def get_dhcp_packet_type(self):
        raise Exception('DHCP packet type filter not fully implemented')


class RyuDHCPOfferFilter(RyuDHCPPacketTypeFilter):
    def get_dhcp_packet_type(self):
        return dhcp.DHCP_OFFER


class RyuDHCPAckFilter(RyuDHCPPacketTypeFilter):
    def get_dhcp_packet_type(self):
        return dhcp.DHCP_ACK


class RyuICMPFilter(object):
    def __call__(self, buf):
        pkt = packet.Packet(buf)
        pkt_icmp_protocol = pkt.get_protocol(icmp.icmp)
        if not pkt_icmp_protocol:
            return False
        return self.filter_icmp(pkt, pkt_icmp_protocol)

    def filter_icmp(self, pkt, icmp_prot):
        return True

    def is_same_icmp(self, icmp1, icmp2):
        if icmp1.data.id != icmp2.data.id:
            return False
        if icmp1.data.seq != icmp2.data.seq:
            return False
        if icmp1.data.data != icmp2.data.data:
            return False
        return True


class RyuICMPPingFilter(RyuICMPFilter):
    """
    A filter to detect ICMP echo request messages.
    :param get_ping:    Return an object contained the original echo request
    :type get_ping:     Callable with no arguments.
    """
    def __init__(self, get_ping=None):
        super(RyuICMPPingFilter, self).__init__()
        self.get_ping = get_ping

    def filter_icmp(self, pkt, proto):
        if proto.type != icmp.ICMP_ECHO_REQUEST:
            return False
        result = True
        if self.get_ping is not None:
            ping = self.get_ping()
            result = super(RyuICMPPingFilter, self).is_same_icmp(proto, ping)
        return result


class RyuICMPPongFilter(RyuICMPFilter):
    """
    A filter to detect ICMP echo reply messages.
    :param get_ping:    Return an object contained the original echo request
    :type get_ping:     Callable with no arguments.
    """
    def __init__(self, get_ping):
        super(RyuICMPPongFilter, self).__init__()
        self.get_ping = get_ping

    def filter_icmp(self, pkt, icmp_prot):
        if icmp_prot.type != icmp.ICMP_ECHO_REPLY:
            return False
        ping = self.get_ping()
        return super(RyuICMPPongFilter, self).is_same_icmp(icmp_prot, ping)


class RyuICMPTimeExceedFilter(RyuICMPFilter):
    """
    A filter to detect ICMP time exceed messages.
    :param get_ip:    Return an object contained the original IP header
    :type get_ip:     Callable with no arguments.
    """
    def __init__(self, get_ip):
        super(RyuICMPTimeExceedFilter, self).__init__()
        self.get_ip = get_ip

    def filter_icmp(self, pkt, icmp_prot):
        if icmp_prot.type != icmp.ICMP_TIME_EXCEEDED:
            return False
        ip_pkt = self.get_ip()
        embedded_ip_pkt, c, p = ipv4.ipv4.parser(icmp_prot.data.data)
        if ip_pkt.src != embedded_ip_pkt.src:
            return False
        if ip_pkt.dst != embedded_ip_pkt.dst:
            return False

        return True


class RyuICMPUnreachFilter(RyuICMPFilter):
    """
    A filter to detect ICMP unreachable messages.
    :param get_ip:    Return an object contained the original IP header
    :type get_ip:     Callable with no arguments.
    """
    def __init__(self, get_ip):
        super(RyuICMPUnreachFilter, self).__init__()
        self.get_ip = get_ip

    def filter_icmp(self, pkt, icmp_prot):
        if icmp_prot.type != icmp.ICMP_DEST_UNREACH:
            return False
        ip_pkt = self.get_ip()
        embedded_ip_pkt, c, p = ipv4.ipv4.parser(icmp_prot.data.data)
        if ip_pkt.src != embedded_ip_pkt.src:
            return False
        if ip_pkt.dst != embedded_ip_pkt.dst:
            return False

        return True


class Action(object):
    """Base class of actions to execute. Actions are executed on matched
    packets in policy rules (PortPolicyRule).
    """
    def __call__(self, policy, rule, port_thread, buf):
        """Execute this action.
        :param policy:      The currently running policy
        :type policy:       Policy
        :param rule:        The rule on which this packet matched
        :type rule:         PortPolicyRule
        :param port_thread: Receiving port
        :type port_thread:  PortThread
        :param buf:         Raw packet data to send
        :type buf:          String (decoded)
        """
        raise Exception('Action not implemented')


class LogAction(Action):
    """Action to log the received packet."""
    def __call__(self, policy, rule, port_thread, buf):
        pkt = packet.Packet(buf)
        LOG.info(_LI('LogAction: Got packet: {}').format(str(pkt)))


class SendAction(Action):
    """Action to send a packet, possibly as a response."""
    def __init__(self, subnet_id, port_id, packet):
        """Create an action to send a packet.
        :param subnet_id: The subnet ID
        :type subnet_id:  Number (opaque)
        :param port_id:   The port ID. With subnet_id, represent a unique port
                in the topology, through which to send the packet.
        :type port_id:    Number (opaque)
        :param packet:    A method that constructs the response from the
                packet's raw data, or a string of a predefined packet.
        :type packet:     (Lambda String -> String), or String (encoded).
        """
        self.subnet_id = subnet_id
        self.port_id = port_id
        self.packet = packet

    def __call__(self, policy, rule, port_thread, buf):
        packet = self.packet
        if not isinstance(packet, str) and not isinstance(packet, bytearray):
            # TODO(oanson) pass more info to the packet generator
            packet = packet(buf)
        self._send(policy, packet)

    def _send(self, policy, packet):
        interface_object = self._get_interface_object(policy.topology)
        interface_object.send(packet)

    def _get_interface_object(self, topology):
        subnet = topology.subnets[self.subnet_id]
        port = subnet.ports[self.port_id]
        return port.tap


class SimulateAndSendAction(SendAction):
    def __init__(self, subnet_id, port_id, packet):
        super(SimulateAndSendAction, self).__init__(subnet_id, port_id,
                                                    packet)
        self.integration_bridge = cfg.CONF.df.integration_bridge

    def _send(self, policy, packet):
        interface_object = self._get_interface_object(policy.topology)
        interface_name = interface_object.tap.name
        port_number = self._get_port_number(interface_name)
        self._simulate(port_number, packet)
        return super(SimulateAndSendAction, self)._send(policy, packet)

    def _get_port_number(self, interface_name):
        ovs_ofctl_args = ['ovs-ofctl', 'dump-ports', self.integration_bridge,
                          interface_name]
        awk_args = ['awk', '/^\\s*port\\s+[0-9]+:/ { print $2 }']
        ofctl_output = utils.execute(
            ovs_ofctl_args,
            run_as_root=True,
            process_input=None,
        )
        awk_output = utils.execute(
            awk_args,
            run_as_root=False,
            process_input=ofctl_output,
        )
        match = re.search('^(\d+):', awk_output)
        port_num_str = match.group(1)
        return int(port_num_str)

    def _simulate(self, port_number, packet):
        packet_str = packet_raw_data_to_hex(packet)
        args = [
            'ovs-appctl',
            'ofproto/trace',
            self.integration_bridge,
            'in_port:{}'.format(port_number),
            packet_str,
        ]
        test_utils.print_command(args, True)


class RaiseAction(Action):
    """Action to raise an exception."""
    def __init__(self, message):
        self.message = message

    def __call__(self, policy, rule, port_thread, buf):
        pkt = packet.Packet(buf)
        raise Exception("Packet {} raised exception on port: {}: {}".format(
            str(pkt),
            (port_thread.port.subnet.subnet_id, port_thread.port.port_id),
            self.message,
        ))


class DisableRuleAction(Action):
    """Action to disable the rule on which the packet matched."""
    def __call__(self, policy, rule, port_thread, buf):
        rule.disabled = True


class StopThreadAction(Action):
    """Action to disable the thread watching the port on which the packet was
    received.
    """
    def __call__(self, policy, rule, port_thread, buf):
        port_thread.stop()


class StopSimulationAction(Action):
    """Action to stop the simulation (i.e. the policy)."""
    def __call__(self, policy, rule, port_thread, buf):
        policy.stop()


class IgnoreAction(Action):
    """A NOP action."""
    def __call__(self, policy, rule, port_thread, buf):
        pass


class WaitAction(Action):
    """Wait the given amount of time"""
    def __init__(self, wait_time):
        self.wait_time = wait_time

    def __call__(self, policy, rule, port_thread, buf):
        time.sleep(self.wait_time)


class PortThread(object):
    """A thread object watching the tap device."""
    def __init__(self, packet_handler, port):
        """Create a thread to watch the tap device.
        :param port:    The tap device to watch
        :type port:     Port
        :param packet_handler: A method to handle a received packet
        :type packet_handler: Function(PortThread, String)
        """
        self.packet_handler = packet_handler
        self.port = port
        self.daemon = d_utils.DFDaemon(is_not_light=True)
        self.is_working = False
        self.thread_id = None

    def start(self):
        self.is_working = True
        self.daemon.daemonize(self.run)

    def stop(self):
        self.is_working = False
        if self.thread_id != threading.current_thread().ident:
            self.daemon.stop()

    def wait(self, timeout=None, exception=None):
        self.daemon.wait(timeout, exception)

    def run(self):
        """Continuously read from the tap device, and send received data to the
        packet handler.
        """
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


class CountAction(Action):
    """Counting times of call, and process an action when reaching threshold"""
    def __init__(self, threshold, action):
        """
        :param threshold:   Value of the threshold.
        :type threshold:    Number (opaque)
        :param action: The action proceeded when times of call reaching
        the threshold.
        :type action:  Action (opaque)
        """
        self.threshold = threshold
        self.cursor = 0
        self.action = action

    def __call__(self, policy, rule, port_thread, buf):
        self.cursor += 1
        if self.cursor == self.threshold:
            self.action(policy, rule, port_thread, buf)
