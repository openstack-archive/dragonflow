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
network node.[2]

The solution proposed here is distributed, in that there is a single proxy
running on each compute node that runs a Dragonflow controller.

The solution proposed here assumes only that the VM has a logical port. It does
not rely on DHCP, or a router. The VM may select any IP address, including
a link-local address, and uses it to communicate with the service.

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
    |      |IP 169.254.13.85   |Metadata service - IP 169.254.169.254
    |   +---------------------------+   |
    |   | OVS switch                |   |
    |   +---------------------------+   |
    |                                   |
    +-----------------------------------+

Note that the above is an example. The VM may select any IP.

The metadata service behaves as a proxy between a VM, and the Nova metadata
service. It processes the HTTP request, and sends an HTTP request to the Nova
metadata service, adding the required headers.

The Nova API that receives the final request is selected by configuration.

A special interface is added: tap-metadata. It is an OVS port used to
communicate with the VMs.

The metadata service listens on an OVS interface, with IP 169.254.169.254, on
a configurable non-standard port. The configuration can specify that the
service will use an ephemeral port. This is so to avoid collision with existing
HTTP services on the host.

To allow VMs to send packets to the metadata service, an ARP responder is
installed for 169.254.169.254, with the MAC address assigned to the
tap-metadata interface. This MAC is not really used, as the connection is
redirected by OVS flows to the metadata service according to IP and port.
However, the VM's network stack requires it.

VMs access the metadata service on IP 169.254.169.254, port 80. VMs are
identified by their in_port. The Dragonflow metadata service retrieves the VM
and tenant ID according to the in_port, and forwards it to the Nova metadata
service.

As part of this forwarding process, the metadata service adds to the HTTP
request the HTTP headers described above.

All IP packets from the tap-metadata interface are treated as directly
routable. This is done by creating an outgoing interface based routing rule to
a routing table where all routes are on the direct network.

This rule will only match packets that already egress via tap-metadata, and
will not affect the network on the rest of the compute node. Additionally,
there will be no networks reachable from the tap-metadata interface in the main
routing table.

For instance, this will be the main routing table on the compute node:

::

    [stack@stack-WefcZf ~]$ ip route
    default via 192.168.121.1 dev eth0
    10.0.0.0/24 via 172.24.4.2 dev br-ex
    172.24.4.0/24 dev br-ex  proto kernel  scope link  src 172.24.4.1
    192.168.121.0/24 dev eth0  proto kernel  scope link  src 192.168.121.157
    192.168.122.0/24 dev virbr0  proto kernel  scope link  src 192.168.122.1

It can be seen that dev tap-metadata has no routes in the main table, and
therefore packets not originating specifically on tap-metadata will not be
routed through it. The routing for tap-metadata is on routing table 2:

::

    [stack@stack-WefcZf ~]$ ip route list table 2
    default dev tap-metadata  scope link

Stating that all packets to all addresses are directly routable. Additionally,
there is a routing rule stating that all packets originating from tap-metadata
are routed via table 2 above. The other rules are default routing rules.

::

    [stack@stack-WefcZf ~]$ ip rule list
    0:      from all lookup local
    32765:  from all oif tap-metadata lookup 2
    32766:  from all lookup main
    32767:  from all lookup default

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
int(src_ip) <- in_port | 0x80000000 (= in_port | int(128.0.0.0)).

In effect, we use the in_port to identify the VM. The in_port is the OF-port
of the port through which the VM made the request. Each port is treated
separately, and therefore this solution works even when a VM has more than one
interface. The service will always reply to the same interface, ignoring the
information that the other ports also reach the same VM.

For example, if a VM's in_port is 13, the packets' source IP is modified to:
128.0.0.13. If the in_port is 1058, the resulting IP is: 128.0.4.34.

A TCP SYN packet that reaches the metadata service table is intercepted by the
controller. The controller installs return flows, and then passes the packet
in the same way as the original flow.

The controller installs an ARP responder mapping the modified IP address to the
MAC address of the VM initiating the request. The ARP responder flow is matched
with the tap-metadata in_port, so that the installed ARP responder can only
affect the metadata service interface. This is preferable to directly changing
the interface's ARP table, since it includes sending a command to OVS, rather
than modifying the Linux kernel via CLI.

Since the output device is selected firstly by the routing table, and the
tap-metadata interface will not appear in the main routing table, only packets
explicitly sent via tap-metadata will be affected by the above ARP responder
flows.

In other words, any packet sent from the compute node will be routed normally.
Packets sent in reply from the metadata service to the VM will be sent via the
tap-metadata interface (since that's the interface bound to the socket), and
these packets will be routed back to the VM via OVS.

The return flows are installed in the metadata service reply table. They detect
the destination VM by the destination IP, which contains the in_port. The flows
then re-set the destination IP to the VMs link-local IP address, and then route
the packet to that VM via the L2 forwarding mechanism.

Note that in this method, the VMs can select conflicting link-local IPs, and
the metadata service will still operate correctly, since the VMs are identified
only by their in_port.

Installed flows
---------------

The following flow is installed in the service classification table:

::

    match=ip,ipv4_dst:169.254.169.254,tcp,tcp_dst=80 action=tcp_dst<-P,resubmit(, METADATA_SERVICE_TABLE)

Where P is the metadata service's ephemeral port, and METADATA_SERVICE_TABLE is
a new table for handling packets to the metadata service. The following flows
are installed there:

::

    match=ip,tcp,+syn-ack priority=high action=output:controller
    match=ip priority=medium action=in_port->src_ip,1->src_ip[0],output:I

where I is the tap-metadata's OFPort. Packets sent from the tap-metadata
interface is redirected to METADATA_SERVICE_REPLY_TABLE.

::

    match=in_port:I action=resubmit(, METADATA_SERVICE_REPLY_TABLE)

Additionally, when the controller receives a SYN packet, it adds a return flow
to METADATA_SERVICE_REPLY_TABLE. Given the VMs IP is X and OFPort is I',
the return flow is:

::

    match=ip,ipv4_dst:(I' | 0x80000000),tcp actions=X->ipv4_dst,80->tcp_src,metadata->metadata,resubmit(,L2_LOOKUP_TABLE)

Where I', X, and metadata are read from the packet-in event in the controller.

Lastly, the ARP responder mapping the VMs' modified IPs to their MAC addresses
is as follows:

::

    match=arp,in_port:I,arp_tsa:(I' | 0x80000000) priority=high actions=<ARP responder>

Where the ARP responder values is also available during the packet-in event.

References
==========

1. http://blog.oddbit.com/2014/01/14/direct-access-to-nova-metadata/
2. https://vietstack.wordpress.com/2014/09/27/introduction-of-metadata-service-in-openstack/
