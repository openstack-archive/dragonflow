
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

======================================
IGMP Application and Multicast Support
======================================

https://blueprints.launchpad.net/dragonflow/+spec/igmp-app

This blueprint describes the addition of an IGMP application, and improvement
in multicast packet handling to DragonFlow. It describes how DragonFlow can
make OVS routers multicast routers, how to handle IGMP packets, and how process
multicast packets such that only group members receive packets of a multicast
group.

Problem Description
===================

The goal of this design is to describe an IGMP application, which will make OVS
virtual routers behave as a multicast-aware routers.

Currently, multicast packets are treated as broadcast packets. They are
duplicated and send to every VM on the immediate subnet. Additionally,
multicast packets cannot be routed accross to other subnets in the same
network.

This blueprint describes how, once a multicast message is received, it will be
sent only to the VMs that are registered to that multicast group. Multicast
packets will be routed to neighbouring subnets, if and only if necessary.
Additionally, multicast packets will be propagated accross compute nodes, so
that other VMs on the same subnet and neighbouring networks on other compute
nodes will also receive the relevant packets.

Use cases:
----------
 * Data Replication
   A single node sending data that needs to be replicated accross multiple
   other server, e.g. backups.

 * Monitoring
   A server sending statistical information e.g. CPU, memory, and bandwidth
   usage, to multiple monitoring agents.

 * Automatic Service Discovery
   Hosts discover services on the network, using e.g. SSDP.

 * Publish/Subscribe
   Publich/Subscribe mechanisms use multicast packets to send published events
   to subscribers without packet multiplication or flooding.

 * Media Streaming
   Media servers multicast video and music to subscribing hosts.

Proposed Change
===============

The proposed change is to implement a Dragonflow IGMP application, in a manner
similar to L2, L3, and DHCP. The IGMP application, once enabled, will make the
OVS router behave as a multicast router, as defined in [1].

There are several elements in [1] that must be implemented.

Multicast packet filtering and routing
--------------------------------------

The application will update the DragonFlow pipeline, and install flows such
that:
 * Every multicast packet is sent only to VM ports that have registered to the
   packet's multicast group. In case the VM has requested source-based filters
   (e.g. only from specific sources, or to exclude specific sources), only
   packets matching the allowed sources will be sent to the VM port. In any
   case, copies of the packet will be created only for cases where the packet
   is actually sent out. The flows will be generated such that the packet will
   not be copied only to be dropped.

 * If there are VMs is on another compute nodes that have registered to the
   multicast group, the packet will be sent to that compute node as well. Note
   that a single encapsulated multicast packet will be sent between compute
   nodes, regardless of the number of VMs that have registered.

 * In case there are multicast group members in neighbouring networks, and only
   then, the packet will be 'routed' to the neighbouring network. It's ttl will
   be reduced by 1, and if it is still greater than 0, the packet will be
   re-inserted to the flow with the in_port set to the router's port.

   Alternatively, since the topology is known in advance, the application can
   calculate how many hops are from a specific subnet to a VM in the network
   (but not a directly neighbouring subnet). If the packet's ttl is greater
   than that number of hops, the ttl can be decreased, and the packet can be
   sent directly to that VMs port. The cost in time and performance of this
   option should be considered before implementation.

Note that in [1], multicast routers address the subnet connected to them as a
whole. However, since the OVS has fine-grained control for every VM port
connected to it, it can filter each packet more accurately to the VMs that
requested it.

For instance, the following flows could be installed by the IGMP application:
classification table:
  match=ip,igmp action=resubmit(,<igmp handler table>)
  match=ip,ip_dst=224.0.0.1 action=resubmit(,<igmp handler table>)
  match=ip,ip_dst=224.0.0.22 action=resubmit(,<igmp handler table>)
  match=ip,ip_dst=224.0.0.0/28 action=resubmit(,<multicast routing table>)

These flows route igmp packets to the igmp handler table, where they'll be sent
to the controller. Packets to 224.0.0.1 and 224.0.0.22, to which the router
must be registered, are also sent there. They will be copied.

This example does not include packets from other compute nodes. Only the
compute node that hosts the VM that created the packet sends it to other
compute nodes. This way, re-sending the same packet over and over is avoided.

igmp handler table:
 match=igmp actions=CONTROLLER
 match= actions=CONTROLLER,resubmit(,<multicast routing table>)

All packets are sent to the controller. Non-IGMP packets may also be sent to
the multicast routing table, if there are other members listening to it.

multicast routing table:
  match=ip_dst=224.0.0.x actions=output:VM1,output:VM2,output:VM3
  match=ip_dst=224.0.0.y actions=output:VM1,output:ComputeNode2
        (via logical tunnel port)
  match=ip_dst=224.0.0.z,ip_src!=10.0.0.100 actions=output:VM2
  match=ip_dst=224.0.0.z,ip_src==10.0.0.100 actions=output:VM3
  match= actions=output:CONTROLLER

These are examples of packets that are sent to the relevant VM ports, including
being sent to another compute node, and including source-based filtering. In
this example, an unknown multicast group is sent to the controller, to allow
reactive programming.

Note that this is a schematic example. For instance, filtering by tenant and
network have not been included.

IGMP packet handling
--------------------

The IGMP application is required to handle all IGMP packets, as well as send
queries, either periodically, or in response to an IGMP packet it had received.

The IGMP application will install flows in the pipeline such that all IGMP
packets will be sent to the controller, and be dispatched to the IGMP
application.

It will periodically send a General Query IGMP packet to all connected subnets.
The period this packet is sent has to be configurable. The packet is sent only
to VMs and external routers. Other Dragonflow routers on the same compute node
already have the needed information, since the IGMP application data is shared.

Once receiving a Memership Report message, it will update the flows described
above to match the new state of affairs. Additionally, whenever a VM
unregisters from a multicast group, it will send to all VMs on the subnet and
the same compute node a Group-Specific Query, to see if there are any group
members left. If there are none, it should update the other compute nodes, so
that multicast packets to that group will not be sent to this compute node.

The IGMP application will keep a record of each VM, to which multicast group it
is registered, and source-based filtering information. This will be used to
accurately update the flows, and to keep them accurate with the current state
of affairs.

Synchronisation accross compute nodes
-------------------------------------

Whenever a group membership state is changed, all compute nodes containing VMs
on the same network need to be updated. To this end, whenever such a change
occurs, the compute node will publish an event advertising this change, to
allow other compute nodes to be updated.

The change event can be published using the publish-subscribe mechanism, via
the Dragonflow database and its publish-subscribe mechanism, or via the Neutron
servers.

In order to reduce publish/subscribe events, an Aggregated Membership Report
Timeout configuration parameter may be set on the compute node. If set, the
compute node waits <Aggregated Membership Report Timeout> seconds since the
first Membership Report packet, and sends in one event an aggregation of all
the information collected at that time. Note that each succeeding packet does
not reset this timer, and if a VM updates its membership once a second, then a
relevant aggregated event will be published every <Aggregated Membership Report
Timeout> seconds.

Router membership to multicast groups
-------------------------------------

Every multicast router must join the multicast group 224.0.0.22, and implement
the protocol as a group member host[1]. The IGMP application will implement all
the details for this behaviour.

The IGMP application will answer general and group-specific queries. When it is
initialised, it will advertise it is a member of that group by sending the
relevant IGMP packet, and it will process all packets sent to that group.

It will modify the pipeline to send a copy of every packet with IP destination
224.0.0.22 to the controller, in addition to sending a copy of this packet out
the relevant ports. The IGMP application will process the packet by registering
to the relevant events on the controller. The IGMP application will gracefully
handle the case where the same packet is received multiple times, since it may
be received from multiple virtual routers. When possible, the flwos installed
in the pipeline will prevent the same multicast packet to be sent to the same
controller multiple times.

IGMPv1 and IGMPv2 support
-------------------------

The supported IGMP version of the routers will be IGMPv3. Processing IGMPv1 and
IGMPv2 packets will be supported as backwards compatibility. Additionally, a
configuration option will be provided to have the router behave as an IGMPv1 or
IGMPv2 router, which are a subset of IGMPv3. i.e. some features e.g. source-
based filtering, will only be available if the correct version is used.

North-South Communication
-------------------------

At the moment, communication to and from networks external to open-stack is not
permitted. However, support can be easily added by allowing the IGMP
application answer IGMP queries with the all registered multicast groups, and
source-based filtering. This information is available to the application.

Additionally, if the application queries the external network, and listens to
incoming IGMP packets, it can add flows to route multicast packets out if and
only if it is relevant.

Additional Configuration
------------------------

Every subnet can be marked whether it supports multicast. If a subnet is marked
not to support multicast, the router ports connected to that subnet are not
multicast routers. They treat IGMP packets as regular routed IP packets. They
do not send periodic general queries, and no multicast packets are never routed
to that subnet. This change will require Neutron integration to support Neutron
API for this configuration.

The IGMPv3 standard defines timers and counters that can be configured. These
configuration parameters can be defined on each switch or router. In case this
is not possible due to integration issues with Neutron, these parameters can be
set globally on the IGMP application. Additionally, the Dragonflow and the IGMP
application can verify that these values are legal and consistent.

OVS multicast snooping
----------------------

OVS has support for multicast snooping. This means that it sniffs IGMP packets
on the network, and can automatically avoid sending multicast packets to VMs
that do not require it on OVS ports[2]. However, it does not support sending
IGMP queries, nor automatically forwarding multicast packets between subnets
over virtual routers. This is the added value of this blueprint.

References
==========

[1] https://tools.ietf.org/html/rfc3376
[2] http://openvswitch.org/support/dist-docs/ovs-vsctl.8.txt

