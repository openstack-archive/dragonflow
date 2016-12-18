=================
Distributed SNAT
=================

Scope
=====

This spec focus on a new, additional SNAT implementation to DragonFlow (which
we will henceforth refer to as "Distributed SNAT") that trades off some
functionality in favor of scale, performance and ease of use (all
highlighted in "Problem Description" section).

All references to IP in this spec refer to IPv4 addressing scheme (IPv6 is
out of scope for this spec).

The main functionality difference between the current DragonFlow
implementation of SNAT and "Distributed SNAT", is that with DragonFlow SNAT
the cloud admin reserves a single external IP address (from a limited
pre-allocated pool), which is used to masquerade multiple VMs of that same
tenant therefore, sharing the same external IP.

With the "Distributed SNAT" solution, in contrast, the cloud admin reserves an
external IP address (from a limited pre-allocated pool) for every [compute
node, tenant gateway] pair/compute node (see Flow section for implementation
alternatives). This way north/south traffic of every VM will be routed out
locally via external IP of hosting compute node.

The main advantage of "Distributed SNAT" is the distribution of the NAT/PAT
function among the compute nodes, bypassing the network node.

The requirement of having dedicated network node will be more flimsy with
"Distributed SNAT" probably apart from VPNaaS deployment.


Problem Description
===================

Currently, when the cloud admin wants to allow multiple VMs to access external
networks (e.g. internet), he/she can either assign a floating IP to each VM
(DNAT), or assign just one floating IP to the router that she uses as a
default gateway for all the VMs (SNAT).

The downside of DNAT is that the number of external IP addresses is very
limited, and therefore it requires that the cloud admin either "switch"
floating IPs between VMs (complicated), or obtain enough external IPs
(expensive).

The downside of SNAT is that all outbound traffic from the VMs that use
it as default gateway will go through the network node that hosts the router,
effectively creating a network bottleneck and single point of failure
for multiple VMs if L3 HA is not deployed.


Proposed Change
===============

This spec outlines an additional SNAT model that places the NAT/PAT on
each compute node. In order for this design to work in a real world
deployment, compute nodes should be attached to external network via the
underlying networking infrastructure.

Such SNAT model is changing the concept of legacy router where single gateway
port is present. Both Neutron DVR and current DragonFlow implementations
follow legacy concept in terms of single gateway port and same internal router
port (in terms of MAC/IP addressing) copied across compute nodes. However this
model redefines single gateway port concept actively defining more than one
gateway port on single distributed router.

When the compute node can route outbound traffic, VMs hosted on it do
not need to be routed through the network node. Instead, they will be
routed locally from the compute node.

Our goal is to preserve Neutron reference implementation and concentrate on
DragonFlow plugin update. Therefore "Distributed SNAT" should NOT be reflected
in Neutron database. DragonFlow plugin should manage additional data on
compute node locally. New model not requires extra Neutron ports on compute
nodes, but it does require every compute node to have IP address on external
network.

This model will take advantage of common DragonFlow deployed component L2 OVS
switch and OpenFlow protocol to achieve "Distributed SNAT" feature
implementation for multi-tenant cloud as local compute node connectivity
enhancement.

In order to achieve DragonFlow pipeline flow change for north/south traffic
new DragonFlow application is required. The easy way to enable/disable
"Distributed SNAT" feature is a presence of SNATApp application in the
application list of DragonFlow configuration file.

DragonFlow controller may monitor external connectvity and perform a fallback
to Neutron SNAT when connectivity outage is detected.


Setup
=====

New DragonFlow application should handle north/south traffic on each compute
node. East/west traffic between VMs of different tenants deployed on different
compute nodes falls into this category as well. Application should handle
local ports (VMs) add/remove events and install/uninstall appropriate
NAT flows as described in Ingress/Egress sections below.

DragonFlow controller should have proper installed rules priorities to
prioritize DNAT over "Distributed SNAT"



Model alternatives
==================

There are number of solutions to achieve "Distributed SNAT". Every solution
has its advantages and weak points.

[1] Single external IP per compute node solution requires double NAT.

Pros:
    - easy to implement
    - requires single external IP address in manual configuration
    - solution consumes #[compute host] external IPs
Cons:
    - all deployed VMs of different tenants have single source IP that is
      reflected outside. If this IP is blacklisted than all tenants VMs on
      this host will 'suffer' service outage.

(*) This solution is chosen as first phase implementation and below
    sections provide details to this solution

[2] Single external IP per compute node solution requires with single NAT and
    port range. Limited number of tenants on compute host. Divide L4 port
    range [1024-65535] between these tenants.
Pros:
    - easy to implement
    - requires single external IP address in manual configuration
    - solution consumes #[compute host] external IPs
Cons:
    - all deployed VMs of different tenants have single source IP that is
      reflected outside. If this IP is blacklisted than all tenants VMs on
      this host will 'suffer' service outage.
    - limited number of tenants on every compute host should be in range
      [1-10] otherwise port range consumed by every tenants in NAT operation
      would be too small

[3] External IP address per [compute node, tenant gateway] pair

Pros:
    - generic solution similar to Neutron in terms of tenants separation
    - blacklisting single tenant will not affect others on same compute host
Cons:
    - more complex implementation in terms of external IPs management
    - solution consumes #[tenants * compute hosts] external IPs


Resources consumption
---------------------

Neutron SNAT implementation consumes number of external IPs equivalent to
number of tenants + single address reserved for gateway on network node.

We want to achieve a reasonably small external IP addresses use and at the
same effort solve a connectivity bottleneck problem. Unfortunately it seems
that none of solution alternatives achieves both targets. However
implementing more than one alternative may give a cloud admin set of tools
to reach desired result in terms of "Distributed SNAT".

In alternative [1], all private networks on br-int IP should be reached via
single static external IP. This scheme requires ARP responder flows for
external IP address similar to floating IP management in DNAT application.


Flow
====

This section describe all the handling in the pipeline for north/south
traffic.

NAT translation can take place natively in OVS that supports NAT feature
starting from version 2.6.x.

OVS native NAT support allows to untie need for linux namespaces required by
Neutron SNAT implementation.

"Distributed SNAT" results a single external IP per compute node. Such
solution requires intermediate NAT from compute node to local cross-tenant
network and then NAT to public external IP.

Below diagram outlines single compute node:


::

        +  Tenant 1       +  Tenant 1         +  Tenant 2
        |  10.0.0.1       |  10.0.0.2         |  10.0.0.1
        |                 |                   |
   +----|-----------------|-------------------|---------------+
   |    \--------\ /------/                   |      br-int   |
   |              v                           v               |
   | cross-tenant | NAT:                      |  NAT          |
   |  private net | 182.0.0.1                 |  182.0.0.2    |
   |              v                           v               |
   |              \-------------\ /-----------/               |
   +-----------------------------v----------------------------+
                                 |  NAT
                     public net  |  172.24.4.2
   +-----------------------------|----------------------------+
   |                             |                    br-ex   |
   +-----------------------------|----------------------------+
                                 v

Local cross-tenant network serves as an intermediate step to translate single
external IP to private IP of specific tenant. The goal is to use cross-tenant
network that is not shared cloud wide. Such implementation reflects
distributed nature of DragonFlow on one hand and allows to preserve Neutron
core implementation unchanged.

This cross-tenant network is used only in terms of separate IP address range
There is no real OVS ports plugged into it. It requires management of tenant
addresses on this network in extra database table on compute node.

Proposed solution is efficient in terms of external IP address use but it may
require extra compute power for connection tracking and extra NAT.

Data model impact
--------------------
VM create/delete operations should update new 'lsnat' table with columns:

  +------+-------------------+-----------------------------------------------+
  | No   |   field           |  Description                                  |
  +======+===================+===============================================+
  | 1.   | tenant id         | unique id to be used in OVS flows             |
  +------+-------------------+-----------------------------------------------+
  | 2.   | neutron tenant id | tenant id ad it appers in neutron DB          |
  +------+-------------------+-----------------------------------------------+
  | 3.   | unique tenant IP  | IP address in cross-tenant local network      |
  +------+-------------------+-----------------------------------------------+
  | 4.   | VM count          | counts VMs of this tenant on local host       |
  +------+-------------------+-----------------------------------------------+

Tenant id and IP fields are further used in OVS flows to implement
intermediate phase of VM to single external IP NAT translation. Neutron tenant
id field links this local table entry and Neutron database.

When new VM is created, compute node gets relevant router update notification
that includes added VM full port information. Local compute node DF plugin
should search local 'lsnat' DragonFlow table for tenant id that
refers to subject of notification port tenant id.

  1. internal OVS port that refer to newly added VM is created
  2. DF controller 'local port added' event is processed

Not found tenant entry should result (3) and (4):

  3. table entry is created
  4. NAT flows for this tenant are created

  5. Increase VM count in table entry anyway
  6. Save updated 'lsnat' table

When VM is deleted, compute node gets relevant router notification that
includes removed VM full port information. DF plugin searches for correct
entry in 'lsnat' table according to tenant id.

  1. internal OVS port representing VM is deleted from 'lport' table
  2. DragonFlow controller 'local port removed' event is processed

Last VM marked in table entry should result (3) and (4):

  3. Remove OVS NAT flows with respect to this tenant
  4. Remove entry in table entry for this tenant

  5. Decrease VM count in table entry anyway
  6. Save updated 'lsnat' table

Note: If DNAT is defined, DNAT rule have precedence over "Distributed SNAT".

Ingress
-------

1. Incoming traffic arrives to br-ex bridge.
2. (*)Packet is routed to br-int and passes reverse NAT to cross-tenant
   network. Tenant ID is identified via connection tracking mark.
3. Tenant connection tracking zone is identified
4. (*)Packet pass another connection tracking. We search tenant specific
   connection tracking table and set a hint for target VM port
5. Packet passes second reverse NAT and routed to regular DragonFlow pipeline
6. Regular DragonFlow pipeline is applied (security groups)

Below is sample implementation of (*) marked steps in OVS flows.

::


  TABLE=0 (INGRESS_CLASSIFICATION_DISPATCH_TABLE)
  table=0, priority=50,ct_state=-new+rel-inv+trk,ip,in_port=1
	actions=ct(table=0,nat),
                move:NXM_NX_CT_MARK[]->OXM_OF_METADATA[0..31],
                resubmit(,15)

  TABLE=15 (INGRESS_NAT_TABLE)
  table=15, priority=50,ct_state=-new+rel-inv+trk,ip
	actions=ct(table=16,zone=OXM_OF_METADATA[0..15],nat),
                   move:NXM_NX_CT_MARK[]->NXM_NX_REG7[0..31]
                   resubmit(,72)


Egress
------

1. Configured DragonFlow pipeline is applied on br-int bridge (conntrack,
   security groups, L2 and L3 lookup)
2. (*)Outgoing packet passes filter for north/south traffic and then NAT flow
   is applied. VM port is stored in connection tracking mark for reverse NAT
   use
3. (*)Second NAT is applied in default connection tracking zone resulting
   external IP as a source address. Connection metadata as stored in
   connection tracking for reverse NAT use
4. Packet get routed to br-ex

Below is sample implementation of (*) marked steps in OVS flows.

::

  TABLE=30 (EGRESS_NAT_TABLE)
  table=30, priority=50, ip
	actions=ct(commit,table=30,zone=OXM_OF_METADATA[0..15],
                   exec(move:>NXM_NX_REG7[]->NXM_NX_CT_MARK[],
                   nat(src=182.0.0.1))),resubmit(,31)

  TABLE=31 (ENGRESS_TENANT_NAT_TABLE)
  table=31, priority=50,ip
	actions=ct(commit,table=31,
                   exec(move:OXM_OF_METADATA[0..31]->NXM_NX_CT_MARK[],
                   nat(src=172.24.4.1))),resubmit(,66)


Configuration
-------------
- host_ip          - static external IP to be used by "Distributed SNAT"
- lsnat_file_path  - location of 'lsnat' table on compute host file system


References
==========

https://bugs.launchpad.net/neutron/+bug/1639566

