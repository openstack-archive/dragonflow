..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===============
Security Groups
===============

https://blueprints.launchpad.net/dragonflow/+spec/security-group-dragonflow-driver

This blueprint describe the addition of security groups support to Dragonflow.
It describes the challenges that Dragonflow implementation for security groups
is trying to solve and how it tackles the scale problems both for data path
performance and control plane performance.


Problem Description
===================

The goal of this design is to describe how we plan to implement Security
groups in Dragonflow.
Instead of using the exact same approach done in Neutron today, we decided to
tackle and improve some of the problems we saw when deploying security groups
at scale.

Current implementation for security groups in Neutron has few problematic
points when deployed at scale that we are trying to solve when we implement in
Dragonflow.

Data path performance
---------------------
Its important to note that Security groups are stateful — responses to allowed
ingress traffic are allowed to flow out regardless of egress rules, and vice
versa. Current Neutron implementation adds a linux bridge in the path between
each port (VM) and OVS bridge.
This linux bridge is configured with IP table rules that implement security
groups for this port. (This was done as iptables couldnt be configured on OVS
ports)

The following diagram demonstrate how the data path looks like:

::

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

In Dragonflow we are already connecting the VMs to the OVS bridge directly,
this design will demonstrate how we plan to leverage OVS connection tracking
integration [1], [2]. With connection tracking integration we will implement
all security group rules using OVS flows and actions with minimum usage of
flows.

Control plane performance
-------------------------
In addition to the data path implementation described above, there are also
RPC challenges for distributing the security group configuration to the local
agents, applying these changes and reacting as fast as possible.

In Neutron current implementation, each VM port has its own, separated process
pipeline for security group, even those VM ports might be associated to same
security groups.

For this reason, changes in VM port configuration (addition/removal) and
changes in security group rules/groups require a complicated process or
re-compiling the rules to iptable chains pipeline and rules.(Something that
sometimes require re-compilation of the entire pipeline)

In Dragonflow we plan to avoid this management problem and define simple
process which avoid the above mentioned problems.

Proposed Change
===============

Solution Guidelines
-------------------
1) Leverage OVS connection tracking for implementing state full rules
2) Using conjunction flows mechanism (supported by OVS 2.4 above[3]) to make
   VM ports configuration about security group and security group rules
   uncoupled.
3) Take security group process of egress rules in source side of packets while
   ingress rules in destination side.

Pipeline Changes
----------------
Egress Side

::

               +---------+    +-----------+    +---------+    +---------+
    +-----+    |         |    |           |    |         |    |         |
    |     |    | Port    |    | Egress    |    | Egress  |    |         |
    | VM  +--> | Security+--> | Connection+--> | Security+--> |   QOS   |
    |     |    |         |    | Tracking  |    | Group   |    |         |
    +-----+    |         |    |           |    |         |    |         |
               +---------+    +-----------+    +---------+    +---------+

Ingress Side

::

    +-----------+    +---------+    +---------+
    |           |    |         |    |         |    +-----+
    | Ingress   |    | Ingress |    | Ingress |    |     |
    | Connection+--> | Security+--> | Dispatch+--> | VM  |
    | Tracking  |    | Group   |    |         |    |     |
    |           |    |         |    |         |    +-----+
    +-----------+    +---------+    +---------+

Design
------
The processes and OVS flows installed for security group egress and ingress
rules are very similar with each other. So we only discuss egress rules below
for example, and will notify the differences between egress and ingress rules
where it is needed.

It also should be announced that all OVS flows mentioned below should be
installed in the OVS integration bridge which could be specified in the
configuration.

1) In the first, Dragonflow controller should install a default OVS flow in
   the egress connection tracking table. That flow will let packets from a VM
   port which isn't associated with any security group and packets without a IP
   header pass through the security group process.
   ::

        priority=1 actions=resubmit(<qos>)

2) When a local VM port is firstly associated to a security group, Dragonflow
   controller will install a OVS flow in the egress connection tracking table,
   to let IP packets from this VM port to do the CT process:
   ::

        in_port=5, ip actions=ct(table=<egress_security_group>, zone=OXM_OF_METADATA[0..15])

   It should be notified that we use the network_id of this VM port saved in
   metadata as the zone id to avoid the addresses overlap problem in CT.

3) In the egress security group table, Dragonflow controller need install OVS
   flows to let packets matched a established/related connection pass and let
   packets with a invalid CT state be dropped:
   ::

       priority=65534, ct_state=-new+est-rel-inv+trk actions=resubmit(<qos>)
       priority=65534, ct_state=-new+rel-inv+trk actions=resubmit(<qos>)
       priority=65534, ct_state=+new+rel-inv+trk actions=ct(commit,table=<qos>,zone=NXM_NX_CT_ZONE[])

4) To applied conjunction flows mechanism, Dragonflow controller will allocate
   a global/local conjunction id and a priority number per security group (if
   locally at each compute node per security group), this is an increasing
   number. The reason of allocating a priority number to each security group is
   the restriction of conjunction flows mechanism in OVS.

5) In the point view of VM ports, when VM ports are applied to a security
   group, Dragonflow controller should install the OVS flows in the egress
   security group table to represent those associating relations, and each
   of those relations will be converted to one OVS flow. This flow carries a
   matchs field contains a VM port identification match (input port number
   for egress side, while reg7 value for ingress side), and a actions field
   contains a conjunction action that uses the conjunction id of this security
   group and a mark to indicate it is the first part of the conjunction flows.
   It should also be mentioned that those flows have the priority number which
   is allocated to this security group:
   ::

       priority=25, in_port=5, ct_state=+new-est-rel-inv+trk actions=conjunctions(20, 1/2)
       priority=25, in_port=6, ct_state=+new-est-rel-inv+trk actions=conjunctions(20, 1/2)

   In addition, if a new VM port is applied to this security group, a new OVS
   flow like above but uses this VM port's identification match should be
   installed.

6) In the point view of security groups, when a security group is associated
   to at least one local VM port, in the egress security group table,
   Dragonflow controller will install OVS flows representing egress rules of
   this security group, and each of those egress rules will be converted to at
   least one OVS flow. This flow carries a matches field contain match items
   in correspondence with one of the egress rules of this security group, and a
   actions field contains a conjunction id of the security group and a mark to
   indicate it is the second part of the conjunction flows. Those flows also
   have the priority number which is allocated to this security group:
   ::

       priority=25, tcp, tp_dst=80, nw_dst=192.168.10.0/24 actions=conjunction(20, 2/2)
       priority=25, tcp, tp_dst=8080, nw_dst=192.168.10.0/24 actions=conjunction(20, 2/2)

   In addition, if a new egress rule is added to this security group, one or
   more new OVS flows like above but match items in corresponded with this new
   rule should be installed.

7) Besides, Dragonflow controller should also install a OVS flow in the egress
   security group table, of which matches field contains the conjunction id
   match of the security group, and actions field contains a CT action to
   commit connection track entries and send packets to the next process table.
   The packets who match at least each one OVS flow of all parts of the
   conjunction flows will meet the match of this OVS flow and do the actions.
   That means those packets match at least one OVS flow mentioned in section 5
   and one OVS flow mentioned in section 6.
   ::

       conj_id=20 actions=ct(commit,table=<qos>,zone=NXM_NX_CT_ZONE[])

8) After all, we should install a default dropping OVS flow with lowest
   priority in the egress security group table to make sure we drop any packet
   that didn't match any of the rules:
   ::

       priority=1 actions=drop

Remote security group in rules
------------------------------
When a security group rule specifies a remote group, for example a ingress
rule in sgA specifies a remote group of sgB, that means only packets from sgB
could match this ingress rule. For converting this part in rule to OVS flows,
we could use all IP addresses of the VM ports which are associated to sgB.
Because those IP addresses could be numerous, aggregating those addresses to
CIDR addresses should be necessary.

Missing Parts
-------------
1) OVS connection tracking integration doesnt yet support IP fragmentation.
   IP defragmentation must be applied before sending the packets to the
   connection tracking module.

References
==========
[1] http://openvswitch.org/support/ovscon2014/17/1030-conntrack_nat.pdf

[2] http://openvswitch.org/pipermail/dev/2014-May/040567.html

[3] http://openvswitch.org/support/dist-docs/ovs-ofctl.8.pdf
