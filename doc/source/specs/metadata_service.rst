..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

========================
Metadata Service Support
========================

https://blueprints.launchpad.net/dragonflow/+spec/neutron-metadata

The metadata service provides a hosted instance the ability to retrieve
instance-specific information via a server on a link-local address.

Problem Description
===================

To receive instance-specific information, the instance sends an HTTP request
to a link-local IP address. A metadata service agent handles the request,
usually proxying it to a Nova service, and proxies the response back.

This allows the instance to retrieve additional configuration information, e.g.

* Public IP

* Public hostname

* Random seed

* SSH public key

* cloud-init script

* user-data provided to nova boot invocation

* Static routing information

More specifically, the virtual instance sends an HTTP request to the link-local
IPv4 address 169.254.169.254. A service listening on that address needs to add
the following HTTP headers, and then forward the request to the nova service.
In effect behaving as a transparent HTTP proxy.

The added headers are:

* X-Instance-ID: The UUID of the virtual instance

* X-Instance-ID-Signature: A cryptographic signature of the Instance-ID[1]

* X-Tenant-ID: The UUID of the tenant

* X-Forwarded-For: The IP of the virtual instance

Currently, there is a solution implemented by Neutron. However, this solution
is implemented in a network node, with a proxy per tenant, and a proxy per
network node.

The solution proposed here is distributed, in that there is a single proxy
running on each compute node that runs a Dragonflow controller.

The solution proposed here assumes only that the VM has a logical port. It does
not rely on DHCP, or a router. The VM selects a link-local address
autonomously, and uses it to communicate with the service.

Proposed Change
===============

The metadata service contains two main elements:

1. Metadata service

2. Dragonflow metadata application

::

    +-----------------------------------+
    |                                   |              +----------+
    |   +-----+         +-------------+ |         +----+ Nova API |
    |   | VM  |         |DF Controller| |         |    +----------+
    |   +-----+         |    +--------+ |         |
    |      |            |    |MD App  | |         |
    |      |            |    +--------+ |         |
    |      |            |    |Metadata| |         |
    |      |            |    |Service +-----------+
    |      |VM port     +-------------+ |
    |      |IP 169.254.0.0/24   |Metadata service - IP 169.254.169.254
    |   +---------------------------+   |
    |   | OVS switch                |   |
    |   +---------------------------+   |
    |                                   |
    +-----------------------------------+

The metadata service behaves as a proxy, between a VM with a link-local IP, and
the Nova metadata service. It processes the HTTP request, and sends an HTTP
request to the Nova metadata service, adding the required headers.

A special interface is added: tap-metadata. It is an OVS port used to
communicate with the VMs.

The metadata service listens on an OVS interface, with IP 169.254.169.254, on
a configurable non-standard port. The configuration can specify that the
service will use an ephemeral port. This is so to avoid collision with existing
HTTP services on the host.

VMs access the metadata service on IP 169.254.169.254, port 80. VMs are
identified by their in_port. The Dragonflow metadata service retrieves the VM
and tenant ID according to the in_port, and forwards it to the Nova metadata
service.

All IP packets from 169.254.169.254 are treated as directly routable. This is
done by creating a source-based routing rule to a routing table where all
routes are on the direct network.

The X-Instance-ID-Signature header is calculated with the hmac algorithm over
the X-Instance-ID header and a shared secret available in /etc/nova/nova.conf.
This is the same mechanism used in the Neutron metadata service.

Since the VMs IP is selected randomly by the VM, it is not registered anywhere.
Therefore, the metadata service sends an arbitrary IP as the X-Forwarded-For
header.

The HTTP client is implemented using httplib2. The HTTP server is implemented
using Neutron's WSGI library.

The dragonflow application adds flows for packets to reach the Dragonflow
metadata service, and for packets to return from the metadata service to the
original VM.

The initial flows that are installed detect connections to 169.254.169.254:80
and re-routes them to the metadata service table.

These initial flows also modify the destination port of the packet to be the
service's listening port.

A return flow detects packets from the metadata service by their in_port. Such
packets are sent to the metadata service reply table.

Packets that reach the metadata service table are forwarded to the metadata
service, via the OVS port 'tap-metadata' mentioned above. The packet's source
IP address is modified to be the in_port. The MSB is set, so that the IP will
appear legal, and will not be dropped by the linux network stack. i.e.
int(src_ip) <- in_port & 0x80000000 (= in_port & int(128.0.0.0).

For example, if a VM's in_port is 13, the packets' source IP is modified to:
128.0.0.13. If the in_port is 1058, the resulting IP is: 128.0.4.34.

A TCP SYN packet that reaches the metadata service table is intercepted by the
controller. The controller installs return flows, and then passes the packet
in the same way as the original flow.

The controller installs an ARP mapping from the modified IP address to the
MAC address of the VM initiating the request. This mapping is installed on
tap-metadata.

The return flows are installed in the metadata service reply table. They detect
the destination VM by the destination IP, which contains the in_port. The flows
then re-set the destination IP to the VMs link-locak IP address, and then route
the packet to that VM via the L2 forwarding mechanism.

Note that in this method, the VMs can select conflicting link-local IPs, and
the metadata service will still operate correctly, since the VMs are identified
only by their in_port.

References
==========

1. http://blog.oddbit.com/2014/01/14/direct-access-to-nova-metadata/
