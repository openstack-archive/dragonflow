..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==================
Security Groups
==================

https://blueprints.launchpad.net/dragonflow/+spec/security-group-dragonflow-driver

This blueprint describe the addition of security groups support to Dragonflow.
It describes the challenges that Dragonflow implementation for security groups is
trying to solve and how it tackles the scale problems both for data path performance
and control plane performance.


Problem Description
===================

The goal of this design is to describe how we plan to implement Security groups in
Dragonflow.
Instead of using the exact same approach done in Neutron today, we decided to
tackle and improve some of the problems we saw when deploying security groups
at scale.

Current implementation for security groups in Neutron has few problematic points
when deployed at scale that we are trying to solve when we implement in Dragonflow

Data path performance
-----------------------
Its important to note that Security groups are stateful — responses to allowed ingress
traffic are allowed to flow out regardless of egress rules, and vice versa.
Current Neutron implementation adds a linux bridge in the path between each port (VM)
and OVS bridge.
This linux bridge is configured with IP table rules that implement security groups
for this port. (This was done as iptables couldnt be configured on OVS ports)

The following diagram demonstrate how the data path looks like:

   +-------------+                     +---------------+
   |             |                     |               |
   |    VM A     |                     |     VM B      |
   |             |                     |               |
   +---+------+--+                     +---+-------+---+
       | eth  |                            |  eth  |
       +--+---+                            +---+---+
          |                                    |
       +--+---+                            +---+---+
       | tap  |                            |  tap  |
 +-----+------+-----+                 +----+-------+-----+
 |                  |                 |                  |
 |   Linux Bridge   |                 |   Linux Bridge   |
 |                  |                 |                  |
 +-----+------+-----+                 +-----+------+-----+
       | veth |                             | veth |
       +--+---+                             +--+---+
          |                                    |
       +--+---+                             +--+---+
       | veth |                             | veth |
+------+------+-----------------------------+------+----------+
|                                                             |
|                     OVS  BRIDGE  (br-int)                   |
|                                                             |
+-------------------------------------------------------------+

In Dragonflow we are already connecting the VMs to the OVS bridge directly, this
design will demonstrate how we plan to leverage OVS connection tracking integration [1], [2].
With connection tracking integration we will implement all security group rules using OVS
flows and actions with minimum usage of flows.

Control plane performance
--------------------------
In addition to the data path implementation described above, there are also RPC challenges for
distributing the security group configuration to the local agents, applying these changes
and reacting as fast as possible.

In order to understand the problems at scale, its important to first understand security
group feature capabilities.

A security rule applies either to inbound traffic (ingress) or outbound traffic (egress).
You can grant access to a specific CIDR range, or to another security group.

When you add a security rule to group Y and set security group X as the source for that rule,
this allows VM ports associated with the source security group X to access VM ports that
are part of security group Y. (The reverse behaviour applies the same for destination)

The default security group is already populated with rules that allows VM ports in
the group to access each other.

The above mentioned capability makes the current process of syncing security group information
difficult because it needs to keep track of all the VM ports and the security group they belong
to and make sure to sync this information on every change to the local agents.
(In current implementation this is managed with ipsets to improve this problem).
More then that, changes in VM port configuration (addition/removal) and changes in security group
rules/groups require a complicated process or re-compiling the rules to iptable chains pipeline
and rules.(Something that sometimes require re-compilation of the entire pipeline)

In Dragonflow we plan to avoid these management problems and define simple process
which avoid the above mentioned problems.

Proposed Change
===============

Solution Guidelines
--------------------
1) Leverage OVS connection tracking for implementing state full rules
2) Avoid the need to recompile or change flows for every VM port add/delete
3) Keep flow number that implement security groups to a minimum
4) Changes to security group rules will replace minimum number of flows


Pipeline Changes
-----------------
The following spec propose two ways to implement security groups in Dragonflow
The following describe the two ways

Common Design to The Two Solutions
-----------------------------------
1) Dragonflow will allocate a global/local id per security group (if locally
  at each compute node per security group), this is an increasing number.

2) On the ingress classification table (table 0) , Dragonflow sets reg6 to
  match the VM port security group id

3) On L2 lookup and L3 lookup tables Dragonflow installs flows which set reg5
  as the destination VM port security group id (at this point the destination VM port
  both for L2 or L3 is known - we are after distributed virtual routing step)
  (Dragonflow sets reg7 as the destination port id)

  *** Its important to note that currently broadcast/multicast traffic is
   duplicated in the source, if we want to duplicate it at the destination, security
   group rules must be applied at destination per VM port as we could have
   different rules for different VM ports in regards to broadcast/multicast ***

4) After classification, Dragonflow sends traffic to connection tracking table.
   We retrieve the connection state of this flow for IP and IPv6 traffic,
   The zone is the same as network id (metadata field)::

     ip, actions=ct(table=<egress_security_group>,zone=metadata)
     ip6, actions=ct(table=<egress_security_group>,zone=metadata)

5) In the egress security table we first match if a connection tracking entry
   exists, if it does (with stat EST) we move to the next table in the pipeline,
   if its invalid state we drop the packet and if the connection state is "NEW"
   we continue checking security rules for Egress::

     priority=65534,ct_state=-new-est+rel-inv+trk, actions=resubmit(,<next_table-egress>)
     priority=65534,ct_state=-new+est-rel-inv+trk, actions=resubmit(,<next_table-egress>)
     priority=65534,ct_state=+inv+trk, actions=drop

6) We then have rules that match for all local security group rules on the outbound side
   (Egress side - traffic leaving the local VM).
   It is very easy to model these rules when we have both the source and destination
   VM ports security group ids identified.
   On match we commit the flow to the connection tracking module with the same zone as the
   source VM network id.

   For example, lets assume we have the following topology:

+----------------------------------------+          +---------------------------------------------+
|                                        |          |                                             |
|   +----------------------+             |          |    +-------------------+                    |
|   |                      |             |          |    |                   |                    |
|   |  VM 1                |             |          |    | VM 2              |                    |
|   |                      |             |          |    |                   |                    |
|   |  Security Group: X   |             |          |    | Security Group: Y |                    |
|   |                      |             |          |    |                   |                    |
|   |                      |             |          |    |                   |                    |
|   |                      |             |          |    |                   |                    |
|   +---------+------------+             |          |    +-----------+-------+                    |
|             |                          |          |                |                            |
|             |                          |          |                |                            |
|             |                          |          |                |                            |
|  +----------+---------------------+    |          |   +------------+------------------------+   |
|  |                                |    |          |   |                                     |   |
|  |              OVS               |    |          |   |                 OVS                 |   |
|  |                                |    |          |   |                                     |   |
|  +--------------------------------+    |          |   +-------------------------------------+   |
+----------------------------------------+          +---------------------------------------------+
                 |                                                         |
                 |                                                         |
                 |                                                         |
                 +---------------------------------------------------------+

   If security group X has the following rule::

      Direction:Egress, Type:IPv4, IP Protocol:TCP, Port Range:Any, Remote IP Prefix:0.0.0.0/0

   This will translate to the following flow::

      match:ct_state=+new+trk,tcp,reg6=X actions=ct(commit,zone=metadata),resubmit(,<next_table>)

   And its also very simple to model if we have the following rule::

       Direction:Egress, Type:IPv4, IP Protocol:TCP, Port Range:Any, Remote Security Group: Y

   This will translate to the following flow::

       match:ct_state=+new+trk,tcp,reg6=X,reg5=Y, actions=ct(commit,zone=metadata),resubmit(,<next_table>)

   With this approach we can model every security group rule to exactly one flow, and
   any changes in VM port additions/deletion don't have to change any of these flows just
   the classification rules for that VM port (which have to change anyway)

   It is also very simple to delete/modify these flows in case of security rule update as
   each rule always only map to a single flow.

7) For both solutions, we need to install flows with lowest priority in the security
   group tables to make sure we drop any IPv4/IPv6 that didn't match any of the rules::

      match:ip,reg7=0x4,reg5=X actions=drop
      match:ipv6,reg7=0x4,reg5=X actions=drop

   And resubmit any other traffic which is not IP to the next table.

At this point the two mentioned solutions differs from each other.

Solution 1 - Perform Full Security Inspection at Source
-------------------------------------------------------

With this solution after the egress security group table (which classified rules for
the local VMs egress policy) we have another table which holds the destination
VM port ingress security group rules converted to flows.

The pipeline looks like this:

    +------------------>------------------------v
    |                                           |
    ^                                           |
    |                                           |
+---+--------+       +------------+      +------v-----+    +-------------+    +-------------+
|            |       |            |      |            |    |             |    |             |
|            |       |            |      | Connection |    |  Egress     |    |  Ingress    |
| L2 Lookup  +-----> | L3 Lookup  +----> | Tracking   +--> |  Security   +--> |  Security   |
|            |       | (DVR)      |      |            |    |  Groups     |    |  Groups     |
|            |       |            |      |            |    |             |    |             |
+------------+       +------------+      +------------+    +-------------+    +-------------+

Converting security group rules to flows is very similar to the above
process but now we use reg5 to indicate the current security group id we inspect and reg6
to mark the source VM port security group id.

*** Due to the state fullness of security groups we must also change table 0 which is receiving
the traffic and dispatching it to destination VM port.
We still need to make sure to commit this flow to connection tracking module at the
destination, this will be used when the destination tries to reply.
This is the only action we need to perform at destination as we already verified all security
rules both for egress and ingress at the source.

Pros
-----
1) We block traffic at the source and avoid sending traffic which will be dropped
at the destination

2) We dont need to pass any additional metadata and hence dont need Geneve tunneling
like solution 2.

Cons
------
1) In this solution we have to install in the ingress security table flows that match
all possible destination VM ports (still one flow per rule)

2) Its problematic if we are doing smart broadcast/multicast distribution as different
security policy can be configured to VM ports in the same broadcast/multicast domain

3) This is problematic for traffic coming from public/external network

Solution 2 - Perform Ingress Security Inspection at Destination
---------------------------------------------------------------

This solution perform the ingress security group classification in the destination
but in order to model security groups classification similar to the model i presented
above, the destination also must know the source VM port security group id.

For this we use Geneve dynamic TLV and pass to the destination the source port
security group id (in addition to the destination VM port id which is written
in the tunnel VNI).

<--- Solution for not using Geneve ---->
Currently the tunnel id is a global mapping between PORT_id --> Tunnel_id.
This is why we need all 24 bits of the VNI field.
However, we can allocate the unique port ids per compute node and manage them
at the plugin.
By doing this we can split the VNI into 14 bits for the port id and
10 bits to carry the src security group id.
With this model we can still deploy this solution but with VXLAN/GRE.
Of course this limit the number of ports per compute nodes and number
of security groups supported.
<----- End ---->

The pipeline for this solution looks like this:

Egress Side

    +------------------>------------------------v
    |                                           |
    ^                                           |
    |                                           |
+---+--------+       +------------+      +------v-----+    +-------------+
|            |       |            |      |            |    |             |
|            |       |            |      | Connection |    |  Egress     |
| L2 Lookup  +-----> | L3 Lookup  +----> | Tracking   +--> |  Security   |
|            |       | (DVR)      |      |            |    |  Groups     |
|            |       |            |      |            |    |             |
+------------+       +------------+      +------------+    +-------------+


Ingress Side

+----------------+       +------------+      +------------+     +--------------+
|                |       |            |      |            |     |              |
| Ingress        |       | Connection |      | Ingress    |     | Dispatch     |
| Classification +-----> |  Tracking  +----> | Security   +---->| to Ports     |
| (Table 0)      |       |            |      | Groups     |     |              |
|                |       |            |      |            |     |              |
+----------------+       +------------+      +------------+     +--------------+

Pros
----
1) Easier to model public/external traffic security groups

2) Can work for optimized L2 broadcast/multicast traffic, we will still need to
   be able to send the source security group id somehow.

3) Require installing security group rule flows only for local ports

Cons
----
1) We have to use Geneve (or other dynamic tunneling) in order to pass the
source security group id number.
(Unless using the trick mentioned above, which limits the number of ports
per compute node and number of security groups)

2) We send traffic to destination even when we can know it is going to be
dropped (We can later introduce a mechanism that sync this information
to drop it at the source if it turns to be problematic)

3) Security group ids must be unique across the setup (global) and must be
allocated from the DF plugin


Missing Parts
--------------
1) OVS connection tracking integration doesnt yet support IP fragmentation.
   IP defragmentation must be applied before sending the packets to the connection
   tracking module.

2) In order to leverage OVS connection tracking the hypervisor must be installed
   with OVS 2.5 and with the relevant kernel module for OVS that adds this
   integration - none are part of official packaging.

References
==========
[1] http://openvswitch.org/support/ovscon2014/17/1030-conntrack_nat.pdf
[2] http://openvswitch.org/pipermail/dev/2014-May/040567.html
