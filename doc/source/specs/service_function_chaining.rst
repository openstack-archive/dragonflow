..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
Service Function Chaining
=========================

https://blueprints.launchpad.net/dragonflow/+spec/service-function-chaining

Problem Description
===================

Service function deployment in a network that supports only destination based
routing can be very time consuming. It requires sophisticated topologies that
have to be maintained manually outside of the tools offered by Neutron.

Recently networking-sfc proposed a change in the API to allow definition of
service function chains and policy based routing (flow classifiers), based
on the architecture described in RFC 7665 [1]_

Proposed Change
===============

Neutron SFC mechanism defines a sequence of port pairs (or groups of) that
represent a service function chains, and classifiers to filter incoming
traffic. [2]_

::

                                         +----------+
                                 Match   | Service  |
                                    +----> function +----+   +-------+
 +--------+       +------------+    |    | chain    |    +---> Dest. |
 | Source |       | Flow       +----+    +----------+    +---> port  |
 | port   +-------> classifier +----+                    |   +-------+
 +--------+       +------------+    | No match           |
                                    +--------------------+


This change will introduce the notion of service function chains to DragonFlow
database and will take advantage of NSH [3]_ and OVS to implement packet
forwarding between service functions.

This spec proposes use of technologies not fully standardized (NSH is an
internet draft at this moment), therefore SFC should be regarded as
experimental feature at this point.

PoC implementation
------------------

Due to above point, and the fact that merging NSH into OVS will take time, we
might start developing using MPLS as the actual carrying protocol, and simulate
SPI/SI and the other features of NSH on top of MPLS labels. This will also aid
in writing the SFC code in a way such that future carrying protocols are easily
pluggable. MPLS is chosen here because it is already supported by OVS.

To implement the following ideas using MPLS we can allocate a label for each
SPI/SI (stored in the NB database), and install flows that will forward the
packet to the relevant SF based on the label. On return, we'll replace the
label with the succeeding one (i.e. the label that is assigned to the next SF
in chain). Metadata that is needed once packet finishes the SFC can be either
stored at the bottom of the MPLS label stack (inner-most labels) or in the NB
database.

As with NSH, we'll have to take MPLS overhead with regard to the MTU.

SFC application
---------------

To implement this change we will introduce a new application inside DF local
controller responsible for forwarding SFC related traffic inside the pipeline
and between the controllers, its primary tasks will be:

+ Classifying traffic from source ports with OVS flows and inserting them into
  the SFC pipeline.
+ Encapsulating packets that match a classifier with the appropriate service
  header  that maps to a correct service function chain, and popping the
  service header once packet reaches the end of the chain.
+ Routing traffic between SFs both locally and between controllers.

We will also have to modify L3/DHCP/DNAT and other application to be aware of
flow classifiers on router/floatingip/dhcp and other kinds of ports. For SFCs
that classify distributed ports, classification will have to happen at all
controllers handling the relevant tenant.

The following figure shows how for each local service function we add a flow
that forwards all packets with appropriate SPI/SI pairs.

::

                                            +---+
               +----------------------+ +--->SF1|
               |NSH table             | |   +---+
 +-------+ NSH |                      | |
 |Table 0+----->SPI=1,SI=1,metadata=1 +-+   +---+
 +-------+     |SPI=2,SI=3,metadata=2 +----->SF2|
               |SPI=2,SI=2,metadata=2 +-+   +---+
               |                      | |
               |SPI=2,SI=1,pop_nsh    | |   +---+
               +----------------------+ +--->SF3|
                                            +---+


We will have to handle 2 types of NSH traffic:

#. Incoming from local SFs - where the local controller will:

   #. Match this traffic with in_port and NSH header
   #. Push relevant network_id and port key,
   #. Forward to service function egress checks (see security concerns)
   #. Dispatch according to NSH forwarding table.

#. Incoming from remote controllers

   #. Match with NSH header, segment_id
   #. Push relevant network_id and port key
   #. Dispatch according to NSH forwarding table.

For each service function local to the controller, we'll create an entry in the
NSH routing table, that will forward all packets with the appropriate SPI, SI
to the SF ingress port. If there SF has more than one instance we have to load
balance between the instances.

Metadata
--------

NSH enables us adding metadata to NSH encapsulated packets passed between
compute nodes and the SFs.

An internet draft dealing with data-center context header allocation [4]_
suggests the following use of context headers (see more info):

::

    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |D| F |R|    Source Node ID     |    Source Interface ID        |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |    Reserved   |               Tenant ID                       |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   | Destination Class / Reserved  |        Source Class           |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                   Opaque Service Class                        |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

We can utilize Source Node ID / Source Interface ID / Tenant ID to match packet
with the tenant/port it originated from. Additionally, we can use Source Class
to pass information of the source network. When we terminate the NSH
encapsulation, and inject the packet into the L2 lookup stage of the pipe we
can use Source Class to determine what network the packet currently resides at.

If we want to enable L3 routing inside SFC, we can utilize Destination Class
field (optional, present when D bit is set), and place the packet in the
network specified by Destination Class field.

For MPLS implementation we can store similar kind of data by pushing several
extra MPLS headers to the packet (before the actual label), and storing the
information in the label fields of the extra headers.

NSH-unaware service functions
-----------------------------

Additional care will be needed for SFs that do not support NSH. We'll have to
implement a proxy that will:

#. Terminate NSH encapsulation right before we pass the packet to the ingress
   port.
#. Add NSH headers to the packet coming from the egress port, and set the
   appropriate SPI and SI. Considering we're setting the NSH header ourselves,
   we can skip the security checks stage for proxied SFs.

A difficulty with NSH-unaware SFs is association of egress packets to paths
when more than one path contains the service function. Depending on the SF it
may or may not be shared among several SFCs.

::

 +------+     +----+      +-------+       +----+       +-------+
 |Egress|     |Push|      |NSH    |       |Pop |       |Ingress|
 |port  +----->NSH +------>routing+------->NSH +------->port   |
 +------+     +-+--+      +-------+       +-+--+       +-------+
                ^                           ^
                |                           |
                +--------+ NSH proxy +------+


Service Path Identifier allocation
----------------------------------

SPI allocation will take place in the DragonFlow code that runs inside Neutron
service, and to avoid conflict between allocated IDs we should use the same
method we use for port tunnel keys, by allocating unique IDs through our
database driver.

We should also reserve a certain range for locally managed SFCs, see Benefits
to DragonFlow section for more details.

Service Function graphs and re-classification
---------------------------------------------

In a recent patch, networking-sfc proposed addition of SFC graphs to implement
service function chains that support re-classification (see bug [5]_ and
patch [6]_). The graph stitches together pairs of SFCs, dest-to-source, to mark
that transition from one SFC to the other is possible.

::

 +----------------------------------------+
 | SFC graph        +-------+   +-------+ |
 |               +-->SFC 2  +--->SFC 4  | |
 |               |  +-------+   +-------+ |
 |  +-------+    |                        |
 |  |SFC 1  +----+  +-------+             |
 |  +-------+    +-->SFC 3  |             |
 |                  +-------+             |
 +----------------------------------------+

To implement this graph we'll have to add forwarding between SFCs as well. For
each SFC of the graph, that has an outgoing edge to another SFC, we will add
flows that match the packet to all the flow classifiers of all the SFCs who
have an incoming edge from the former SFC. (E.g. in the figure above, all the
packets that come out of SFC1 will be forwarded to flow classifiers of SFC2 and
SFC3).

Load balancing
--------------

Neutron service function chaining [7]_ document specifies that when multiple
service function instances are defined for the same stage of the SFC (multiple
port pairs in port pair group), then service function chaining mechanism should
distribute the load according to the weight defined for each service function.

It also states that load balancing should be both optionally sticky and
non-sticky.

For non-sticky load balancing we can use OVS group actions with select type,
and bucket weights to model the load distribution.

Sticky load balancing will be implemented using LBaaS once it becomes available

Changes to the object model
---------------------------

This change will introduce DB objects that match their design to the respective
objects in Neutron:

Port pairs:

.. code-block:: json

 {
     "id": "ID of port pair",
     "correlation_mechanism": "NSH/MPLS/none",
     "ingress_port_id": "ID of the ingress port for SF",
     "egress_port_id": "ID on the egress port for SF"
 }


Port pair groups:

.. code-block:: json

 {
     "id": "ID of port pair group",
     "port_pairs": [
         {
             "port_pair_id": "ID of the port pair object",
             "weight": "Weight of the port pair for LB purposes"
         },
         "Zero or more port pairs"
     ]
 }

Service function chains:

.. code-block:: json

 {
     "id": "ID of the SFC",
     "name": "Name of the SFC",
     "tenant_id": "Tenant ID of the SFC",
     "proto": "NSH/MPLS",
     "service_path_id": "Identifier of this SFC",
     "port_pair_groups": [
         "First port pair group ID",
         "Zero or more port pair group IDs"
     ]
     "flow_classifiers": [
         {
             "name": "Flow classifier name",
             "ether_type": "IPv4/IPv6",
             "protocol": "IP protocol",
             "source_cidr": "Source CIDR of incoming packets",
             "dest_cidr": "Destination CIDR of incoming packets",
             "source_transport_port": "[min, max]",
             "dest_transport_port": "[min, max]",
             "source_lport_id": "ID of source port",
             "dest_lport_id": "ID of destination port",
             "l7_parameters": "Dictionary of L7 parameters"
         },
         "More flow classifier definitions"
     ]
 }

Service function chain graphs:

.. code-block:: json

 {
     "id": "SFC graph ID",
     "tenant_id": "Tenant ID of the graph",
     "edges": [
         ["ID of outbound SFC", "ID of inbound SFC"],
         "Zero or more SFC pairs"
     ]
 }

Security concerns
-----------------
User deployed service functions have full control over the packets they produce
and can take advantage of that to inject invalid or malicious packets into the
integration bridge. For this matter, a valid packet is one that does not intend
to harm the network or its resources.

We can perform several checks on SF egress packets:

#. Check if the packet is NSH encapsulated, if not, apply the original pipeline
   (port sec, security groups, firewall, ...)
#. Check that SPI on the packet maps to a valid SFC in the database that
   belongs to the same tenant as the service function.
#. Check that SI on the packet maps to the next hop in the SFC (Neutron's API
   does not take into account re-classification at service function nodes)

The above steps can be implemented using flows in OVS

::

 +------------+           +---------------+         +-------------+
 | SFC egress |  NSH      | NSH security  |         | NSH routing |
 | port       +-----------> checks        +--------->             |
 |            |           |               |         |             |
 +--------+---+           +---------------+         +-------------+
          |
          |               +---------------+
          |     Not NSH   | Regular       |
          +---------------> pipeline      |
                          |               |
                          +---------------+

Benefits to DragonFlow
----------------------
This change can help simplify DragonFlow's pipeline, as now we can define our
apps (now service functions) with much less coupling to each other, and let the
service function app drive the messages between them.

For example, for each packet originating from the VM port on the compute, we
can define the following SFC:

* Port security
* Security groups
* Firewall
* Quality-of-Service
* etc

::

                +-------------------------------------+
  +------+      | Egress service function chain       |
  |  VM  |      |  +-----+  +----+  +----+  +-----+   |
  | port |------+->| Port|->| SG |->| FW |->| QoS |---+-->....
  +------+      |  | sec.|  | SF |  | SF |  | SF  |   |
                |  +-----+  +----+  +----+  +-----+   |
                +-------------------------------------+

SFC as above does not require SFs on another compute nodes, more so each
controller has their own copy of this SFC. There is no need to hold info about
this SFC in the database as it can be considered internal/private.

In order to avoid collisions we need to reserve an SPI range for such
controller-internal SFCs.

Additionally, since all the apps are implemented using flows (and packet-in),
we can forward packets directly to the table managed by the app and the app
can forward the packet back to NSH dispatch table.

Tests
-----

#. Flow classification - we should check that given a type of logical port we
   install the correct flows to intercept the traffic flowing from or towards
   it:

   - VM ports
   - Router ports and gateway port
   - Floating IP's port
   - DHCP agent port

#. Traversing the SFC - given an SFC and SF layout, we can check that our
   packet takes a logical route and visits all SFs in a logical order.

#. Graphs - re-classification occurs only between SFCs that are part of the same
   graph


Work Items
----------
#. Items for Ocata

   #. Implement a DragonFlow SFC driver and the relevant parts of north-bound
      API.
   #. Implement the DragonFlow controller app that manages the flows based on
      the SFCs relevant to the controller.

      #. First implementation might be based on MPLS.

   #. Testing

#. Items for Pike

   #. Implement SFC "port security" mechanism.
   #. Propose design for internal SFCs

We would also have to make sure openvswitch NSH patches [8]_ get merged, and
RYU support for NSH is added.

References
==========
.. [1] https://tools.ietf.org/html/rfc7665

.. [2] http://docs.openstack.org/developer/networking-sfc/api.html

.. [3] https://tools.ietf.org/html/draft-ietf-sfc-nsh-10

.. [4] https://tools.ietf.org/html/draft-guichard-sfc-nsh-dc-allocation-05

.. [5] https://bugs.launchpad.net/networking-sfc/+bug/1587486

.. [6] https://review.openstack.org/#/c/388802

.. [7] https://wiki.openstack.org/wiki/Neutron/ServiceInsertionAndChaining#Overview

.. [8] https://github.com/yyang13/ovs_nsh_patches
