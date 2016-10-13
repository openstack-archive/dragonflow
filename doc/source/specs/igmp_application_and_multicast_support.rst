..
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

We implement an IGMP Agent as a Dragonflow application, which installs
a classifier to detect IGMP messages on the egress port of the VM.

The IGMP Agent is responsible for forwarding multicast messages only to VMs
that are registered to that multicast group, while respecting the filtering
fields that are defined in IGMPv3. VM registration is detected by processing
IGMP Join packets that all subscribed VMs send.

Multicast packets will be forwarded to sibling subnets on the network, only
if necessary, i.e. VMs exist on those networks that subscribe to the
particular multicast group.

Forwarding of the multicast packets will be done in the overlay network. By
recording in the distributed database to what multicast group a VM is
registered, we know which Compute Nodes need to receive a copy of each packet.

Routing multicast packets to the physical network will be handled in another
blueprint.


Use cases
---------
 * Data Replication - Replicating data of a single node to a group of other
   nodes, e.g. for backup, disaster recovery, etc.

 * Monitoring - A node broadcasting statistical information (e.g. CPU, memory,
   bandwidth usage, etc.) to a group of monitoring agents

 * Automatic Service Discovery - Nodes discover services on the network, e.g.
   using SSDP.

 * Publish / Subscribe - Publish events to subscribers without the publisher
   knowing about the subscribers

 * Media Streaming

 * Targeted broadcast - Broadcast packets only to a subset of networks. e.g.
   send broadcast traffic for a certain virtual network.

Proposed Change
===============

We will implement the Dragonflow IGMP Agent application, in a manner similar
to other Dragonflow applications (e.g. DHCP), following the specifications
according to [1] as detailed below.

The IGMP Agent application is optional, and needs to be enabled by the user.

Multicast packet filtering and routing
--------------------------------------

Extend the Dragonflow pipeline with flows that implement the following:

 * Multicast packet (MCP) is only forwarded to ports that are registered to the
   same group.

 * MCP is only forwarded to ports that fulfill source-based filters specified
   by the registering port (e.g. exclude specific sources, allow only specific
   sources).

 * MCP is only forwarded to compute nodes that have valid ports, in order to
   reduce unnecessary copies.

 * Only 1 MCP is forwarded to a compute node that hosts one or more relevant
   registered ports. The IGMP Agent application on the compute node will
   forward the MCP locally to all the relevant ports.

 * If the TTL on the MCP is greater than 1, and there are relevant registered
   ports on connected networks, the MCP will be forwarded to the relevant
   routers, where its TTL will be reduced by 1 and its in_port changed to the
   router's port.

 * An alternative approach assumes the topology is known in advance, so the
   IGMP Agent application can calculate the distance (in hops) to registered
   ports and then forward the MCP directly to ports that fall within the
   acceptable distance, while reducing the TTL accordingly.

 * MCPs and MCP-related flows may bypass other applications such as L2, L3, and
   dhcp, but **must not** bypass the security group flows. Security group
   policies must be allowed to affect MCPs.

Note that according to [1], multicast routers address the subnet connected to
them as a whole. However, with the Dragonflow SDN controller, we know exactly
which ports are registered for any given MCP, and can therefore directly target
the forwarded MCP to these ports, instead of a more wasteful flooding approach.

Multi-tenancy filtering is handled trivially. Since tenants do not share
subnets and networks, multicast packets will not be routed from the VM of one
tenant to the VM of another.

It is important to make sure that MCPs are processed by security group rules
flows as well.

As a simpler alternative, blocking MCPs from reaching specific ports can be
done using security groups. e.g. adding a security group rule where a packet
cannot be routed back to its source. Note that the original implementation is
preferable, since it allows the multicast application to be standalone, and
not depend directly on additional applications. This alternative should only be
used if the original implementation fails, and it put here for completeness
only.

Example
^^^^^^^

The following flows can be installed by the IGMP Agent application into the
Dragonflow pipline *classification* table, in order to classify IGMP packets
and resubmit them to the *IGMP Handler* table, where they will be handled by
the IGMP Agent application in the controller.

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
Agent application in Dragonflow) to enable reactive programming.

For the sake of clarity and simplicity, we have omitted filtering by tenant
and network from this example.

Databse Structure
-----------------

VM group registration information is stored in the *Multicast* table in the DF
database.

The fields in the *Multicast* table are as follows:

* The VMs that are registered to the multicast group
* For each VM

  * Source filtering method, which can be exclude/include
  * Source IPs to filter, according to the method.
  * Whether this configuration can be affected by IGMP packets, or is it
    configured externally.

More formally:

 *Multicast* : Multicast group -> Multicast record (Type: *List of Multicast
 record*)

 *Multicast record*: VM (Type: *VM UUID*), Source filtering method
 (Type: *'INCLUDE' or 'EXCLUDE'*), filter IPs (Type: *List of IP*), is
 external configuration (Type: *Boolean*)


IGMP packet handling
--------------------

The IGMP application (IGMP-A) handles all IGMP packets, and sends periodic and
response queries to IGMP packets it receives.

The IGMP-A installs specific flows in the Dragonflow pipeline in
order to have all IGMP packets forwarded to it.

The IGMP-A periodically (configurable) sends a *IGMP General Query* MCP to all
ports.

The IGMP-A updates flows according to *Membership Report* messages.

The IGMP-A registers to handle packets sent to 224.0.0.22 and extends the
Dragonflow pipeline to forward all such packets to the controller and to
all other relevant ports.

The IGMP-A is tolerant to duplicate packets, although we believe we can
prevent MCPs to be sent to the same target multiple times.

Manual multicast topology configuration
---------------------------------------

As an alternative to IGMP multicast handling, IGMP-A may be configured with the
information of which VM belongs to which multicast group.

Such configuration of a VM is done directly with the *Multicast* table in the
DF distributed database. When such a configuration is set, the *is external
configuration* flag on the Multicast/VM record is set. IGMP packets sent from
that VM no longer affect which multicast packets are routed to the VM.

Synchronization with local ports
--------------------------------

The IGMP-A keeps records on the registration and unregistration of all local
ports, including source filtering preferences (method and IP addresses).

The IGMP-A may send periodic *Group-Specific Query* message to all local ports
and synchronize its records.

Synchronization across compute nodes
-------------------------------------

The IGMP-A shares aggregated information with its peers (i.e. all multicast
groups the compute node is registered to) by writing to the *Multicast* table
in the Dragonflow distributed database.

All IGMP-A instances on all compute nodes subscribe to changes on the
*Multicast* table and update their local flows per these changes.

For performance optimization, we provide a configurable parameter
<aggregated membership report interval> that defines the minimal time
between updates of the *Multicast* table, in order to quiesce noisy ports
that change their membership too often.

Router membership to multicast groups
-------------------------------------

The IGMP-A implements the Multicast Virtual Router (MCVR) behaviour, according
to the IGMP specs [1]:

* MCVR is required to join the multicast group 224.0.0.22
* MCVR is required to implement the IGMP protocol as a group member
  host[1]
* MCVR is required to respond to general and group-specific queries
* MCVR should advertise its group membership
* MCVR should process MCPs forwarded to, if it is registered to the MCP's
  multicast group.

Supported IGMP Versions
-----------------------

The Dragonflow IGMP-A will implement IGMPv3, and also provide backward-
compatibility to IGMPv1 and IGMPv2.
A configuration parameter will define which IGMP version is provided.

North-South Communication
-------------------------

Communication to and from networks external to openstack and dragonflow are not
handled in this spec. This will appear in a separate blueprint.

This spec assumes that communication between compute nodes is done over a
tunneling protocol, e.g. vxlan, and geneve. VLAN communication between compute
nodes is beyond the scope of this document.

Additional Configuration
------------------------

We propose the following new configuration:


 *Subnet*
    *enable-igmp* : Boolean - Will IGMP, and by extension, multicast, be
      supported on this subnet. If true, this spec is applied. If false, all
      router ports connected to this subnet are not multicast routers. IGMP
      packets are treated as regular routed IP packets. MCPs are not routed to
      sibling networks. IGMP queries are not sent. Default - True
    *robustness-variable* : Integer - The robustness variable as defined in [1].
      While not used directly, it is used to calculate the *Group membership
      interval*, default values for *Startup query count*, and *Last member
      query count*. Default - 2
    *query-interval* : Integer - the interval between General Queries sent by
      the MCVR. Default - 125 (Seconds)
    *query-response-interval* : Integer - used to calculate the maximum amount
      of time a IGMP group member may respond to a query. Default - 10 (Seconds)
    *startup-query-interval* : Integer - the interval between General Queries
      sent by an MCVR on startup. Default - 1/4 of *query-interval*
    *startup-query-count* : Integer - number of Queries sent out on startup,
      separated by the *startup-query-interval*. Default - *robustness-variable*
    *last-member-query-interval* : Integer - used to calculate the maximum
      amount of time an IGMP group member may respond to a group-specific query
      sent in response to a leave message. Default - 1 (Seconds)
    *last-member-query-count* : Integer - number of Group-Specific Queries
      sent before the router assumes there are no group members in this subnet.
      Default - *robustness-variable*
 *Chassis*
    *aggregated-membership-report-interval* : Integer - Amount of time to wait
      for and aggregate events before updating the DF database. Default - 10
      (seconds)


The table structure in the distributed dragonflow database will hold a record
per subnet. The key will be the subnet's UUID.

The record value will be a JSON string representing a map from configuration
name to its value, with a *subnet-id* field containing the subnet's UUID.

Pending Neutron integration, the configuration API will also verify that these
parameters will contain valid values, and fail the configuration command
otherwise.

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
