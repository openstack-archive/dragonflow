
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

======================================
IGMP Application and Multicast Support
======================================

https://blueprints.launchpad.net/dragonflow/+spec/igmp-app

This blueprint describes the addition of an IGMP application and improvement
in virtual multicast packet handling to Dragonflow.
We describe how Dragonflow can implement multicast routers using OVS, by
handling IGMP and multicast packets while ensuring that only group members
within the tenant network receive packets of a multicast group.

Problem Description
===================

Currently, multicast packets are treated as broadcast packets. They are
duplicated and sent to every VM on the subnet. Additionally, multicast
packets cannot be routed across to other subnets in the same network.


Proposed Solution
=================

We implement an IGMP Proxy as a Dragonflow application, which installs
a classifier to detect IGMP messages on the egress port of the VM.

The IGMP Proxy app is responsible for forwarding multicast messages only to
VMs that are registered to that multicast group (which we detect by the IGMP
Join that all subscribed VMs send), while respecting the filtering fields
that are defined in IGMPv3.

Multicast packets will be forwarded to sibling subnets on the network, only
if necessary, i.e. VMs exist on those networks that subscribe to the
particular multicast group.

Forwarding of the multicast packets will be done in the overlay network,
using the MAC (L2) population to discover which Compute Nodes need to
receive a copy of each packet.


Use cases
---------
 * Data Replication - Replicating data of a single node to a group of other
   nodes, e.g. for backup, disaster recovery, etc.

 * Monitoring - A node broadcasting statistical information (e.g. CPU, memory,
   bandwidth usage, etc.) to a group of monitoring agents

 * Automatic Service Discovery - Nodes discover services on the network, e.g.
   using SSDP, etc.

 * Publish / Subscribe - Publish events to subscribers without the publisher
   knowing about the subscribers

 * Media Streaming

Proposed Change
===============

We will implement the Dragonflow IGMP Proxy application, in a manner similar
to other Dragonflow applications (e.g. DHCP), following the specifications
according to [1] as detailed below.

The IGMP Proxy application is optional, and needs to be enabled by the user.

Multicast packet filtering and routing
--------------------------------------

Extend the Dragonflow pipeline with flows that implement the following:

 * Multicast packet (MCP) is only forwarded to ports that are registered to the
   same group.

 * MCP is only forwarded to ports that fulfill source-based filters specified
   by the registering port (e.g. exclude specific sources, allow only specific
   sources, etc.).

 * MCP is only forwarded to compute nodes that have valid ports, in order to
   reduce unnecessary copies.

 * Only 1 MCP is forwared to a compute node that hosts one or more relevant
   registered ports.  The IGMP Proxy application on the compute node will
   forward the MCP locally to all the relevant ports.

 * If the TTL on the MCP is greater than 1, and there are relevant registered
   ports on connected networks, the MCP will be forwarded to the relevant
   routers, where its TTL will be reduced by 1 and its in_port changed to the
   router's port.

 * An alternative approach assumes the topology is known in advance, so the
   IGMP Proxy application can calculate the distance (in hops) to registered
   ports and then forward the MCP directly to ports that fall within the
   acceptable distance, while reducing the TTL accordingly.

Note that according to [1], multicast routers address the subnet connected to
them as a whole. However, with the Dragonflow SDN controller, we know exactly
which ports are registered for any given MCP, and can therefore directly target
the forwarded MCP to these ports, instead of a more wasteful flooding approach.

Example
^^^^^^^

The following flows can be installed by the IGMP Proxy application into the
Dragonflow pipline *classification* table, in order to classify IGMP packets
and resubmit them to the *IGMP Handler* table, where they will be handled by
the IGMP Proxy application in the controller.

*classification* table

::

  match=ip,igmp action=resubmit(,<igmp handler table>)
  match=ip,ip_dst=224.0.0.1 action=resubmit(,<igmp handler table>)
  match=ip,ip_dst=224.0.0.22 action=resubmit(,<igmp handler table>)
  match=ip,ip_dst=224.0.0.0/28 action=resubmit(,<multicast routing table>)

Packets to 224.0.0.1 and 224.0.0.22, to which the router must be registered,
are also sent there. They will be copied.

This example does not include packets from other compute nodes. Only the
compute node that hosts MCP originator forwards it to other compute nodes.
This way we avoid re-sending the same packet in an endless loop.

*IGMP Handler* table:

::

 match=igmp actions=CONTROLLER
 match= actions=CONTROLLER,resubmit(,<multicast routing table>)

All packets are sent to the controller. Non-IGMP packets may also be sent to
the multicast routing table, if there are other members listening to it.

*Multicast Routing* table:

::

  match=ip_dst=224.0.0.x actions=output:VM1,output:VM2,output:VM3
  match=ip_dst=224.0.0.y actions=output:VM1,output:ComputeNode2
        (via logical tunnel port)
  match=ip_dst=224.0.0.z,ip_src!=10.0.0.100 actions=output:VM2
  match=ip_dst=224.0.0.z,ip_src==10.0.0.100 actions=output:VM3
  match= actions=output:CONTROLLER

These are examples of packets that are sent to relevant ports on the local
compute node, or on another compute node, and included source-based filtering.
We forward MCP on unknown multicast group to the controller (i.e. the IGMP
Proxy application in Dragonflow) to enable reactive programming.

For the sake of clarity and simplicity, we have omitted filtering by tenant
and network from this example.

IGMP packet handling
--------------------

The IGMP application (IGMP-A) handles all IGMP packets, sends periodic and/or
response queries to IGMP packets it receives.

The IGMP-A installs specific flows in the Dragonflow pipeline in
order to have all IGMP packets forwarded to it.

The IGMP-A preiodically (configurable) sends a *IGMP General Query* MCP to all
ports.

The IGMP-A updates flows according to *Membership Report* messages.

The IGMP-A registers to handle packets sent to 224.0.0.22 and extends the
Dragonflow pipeline to forward all such packets to the controller and to
all other relevant ports.

The IGMP-A is tolerant to duplicate packets, although we believe we can
prevent MCPs to be sent to the same target multiple times.

Synchronization with local ports
--------------------------------

The IGMP-A keeps records on the registration and unregistration of all local
ports, including source filtering preferences (method and IP addresses).

The IGMP-A may send periodic *Group-Specific Query* message to all local ports
and synchronize its records.

Synchronization across compute nodes
-------------------------------------

The IGMP-A shares aggregated information with its peers (i.e. all multicast
groups the compute node is registered to) by writing to the Dragonflow
distributed database, in a specific *Multicast* table.

All IGMP-A instances on all compute nodes subscribe to changes on the
*Multicast* table and update their local flows per these changes.

For performance optimization, we provide a configurable parameter
<aggregated membership report interval> that defines the minimal time
between updates of the *Multicast* table, in order to quiesce noisy ports
that change their membership too often.

Router membership to multicast groups
-------------------------------------

The IGMP-A implements the Multicast Router (MCR) behaviour, according
to the IGMP specs [1]:

* MCR is required to join the multicast group 224.0.0.22
* MCR is required to implement the IGMP protocol as a group member
  host[1]
* MCR is required to respond to general and group-specific queries
* MCR should advertise its group membership
* MCR should process MCPs forwarded to it that belong to one or more of the
  groups it is registered to

Supported IGMP Versions
-----------------------

The Dragonflow IGMP-A will implement IGMPv3, and also provide backward-
compatibility to IGMPv1 and IGMPv2.
A configuration parameter will define which IGMP version is provided.

North-South Communication
-------------------------

At the moment, communication to and from networks external to openstack is not
permitted. However, support can be easily added by allowing the IGMP
application answer IGMP queries with the all registered multicast groups, and
source-based filtering. This information is available to the application.

To support external communication, the IGMP application will have to generate
IGMP queries and replies on the external interface. The reply information can
be generated from the information stored in the Dragonflow distributed DB.

The IGMP application will also have to forward out multicast packets. In
particular, multicast packets for groups 224.0.0.2 and 224.0.0.22, which are
used by routers to detect the multicast topology, will have to be forwarded.
Provided, of course, that that TTL of those packets is not too low.

By processing IGMP packets received, the IGMP application keeps track of the
multicast groups active on external networks. It will update the multicast
routing flows accordingly, such that only multicast packets targetted at groups
registered externally, will be forwarded out.

In essence, the treatment of the external port will be similar to a regular
router port in a physical network. IGMP packets are processed, multicast groups
and group members are recorded, and multicast packets are forwarded out only
when relevant. Additionally, timers can be used to periodically query the
external network for remaining group members, ad defined in the RFC[1].

The IGMP application will use the information in the Dragonflow distributed DB
to respond to queries. Additionally, it will send group membership reports
whenever a VM becomes a member of a new group, or the sum of the source-based
filtering criteria changes.

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
