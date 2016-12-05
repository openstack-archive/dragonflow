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
nodes, but it does require every compute node external bridge (br-ex) to have
IP address on external network.

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

Flow
====

This section describe all the handling in the pipeline for north/south
traffic.

NAT translation can take place natively in OVS that supports NAT feature
starting from version 2.6.x.

OVS native NAT support allows a clean SDN implementation.


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

NB data model impact
--------------------
VM create/delete operations may update new 'lsnat' table with columns:

  +------+-------------------+-----------------------------------------------+
  | No   |   field           |  Description                                  |
  +======+===================+===============================================+
  | 1.   | tenant id         | unique id to be used in OVS flows             |
  +------+-------------------+-----------------------------------------------+
  | 2.   | neutron tenant id | tenant id ad it appers in neutron DB          |
  +------+-------------------+-----------------------------------------------+
  | 3.   | unique tenant IP  | IP address in cross-tenant local network      |
  +------+-------------------+-----------------------------------------------+

Tenant id and IP fields are further are used in OVS flows to implement
intermediate phase of VM to sinle external IP NAT translation. Neutron tenant
id field links NB and Neutron databases.

When new VM is created, compute node gets relevant router update notification
that includes added VM full port information. Local compute node DF plugin
should search local 'lsnat' DragonFlow database table for tenant id that
refers to subject of notification port tenant id.
Not found tenant entry should result:

1. internal OVS port that refer to newly added VM is created
2. 'lsnat' table update with new tenant id and random IP in cross-tenant
   network range
3. DF controller 'local port added' event is processed
4. DF-controller SNAT application adds OVS flows relevant for newly added VM
   SNAT traffic

Otherwise all action items except (2) should be perfomed

When VM is deleted, compute node gets relevant router notification that
includes removed VM full port information. DF plugin should count entries
in DragonFlow database 'lport' table for tenant id that refers to subject of
notification port tenant id.

1. If single entry is found - tenant entry deleted from 'lsnat' table
2. intenal OVS port representing VM is deleted from 'lport' table
3. DragonFlow controller 'local port removed' event is processed
4. DF-controller SNAT application deletes OVS flows relevant for deleted VM
   SNAT traffic

Note: If DNAT is defined, DNAT rule have precedence over "Distributed SNAT".

Ingress
-------

1. Incoming traffic arrives to br-ex bridge.
2. (*)Packet is routed to br-int and passes reverse NAT to cross-tenant
   network
3. Tenant connection tracking zone is identified
4. (*)Packet pass another connection tracking (specific zone conntrack table)
5. Packet passes second reverse NAT and routed to regular DragonFlow pipeline
6. Regular DragonFlow pipeline is applied (security groups)

Below is sample implementation of (*) marked steps in OVS flows. We use
NXC_NX_REG8 register to save tenant id between different connection tracking
zones and different flow tables:

::

  Ingress traffic phase #1: ( table 30 - ingress tenant NAT traffic )
  External originating traffic match drop rule
  Returning traffic passes default zone connection tracking table,
  resulting following actions:
   - packet passes tenant NAT
   - connection mark that refer to tenant ID set to internal OVS register

    table=30, in_port=patch_ex, ct_state=+new, actions=drop
    table=30, in_port=patch_ex, ct_mark=tenant1, zone=default, ct_state=+est,
        actions=ct(nat), load:tenant1->NXM_NX_REG8[], resubmit(, 31)


  Ingress traffic phase #2: (table 31 - ingress NAT traffic)
  Returning tenant traffic passes second NAT when connection tracking zone
  matches tenant incoming port, resulting following actions:
   - packet passes NAT
   - packet is routed to tap port of specific VM according to connection mark

    table=31, ct_mark=VM1, ct_zone=NSM_NX_REG8, ct_state=+est,
        actions=ct(nat), output=VM1

  Table 15 has one flow per locally deployed VM
  Table 16 may have single flow for all tenants due to saved tenant id

Egress
------

1. Configured DragonFlow pipeline is applied on br-int bridge (conntrack,
   security groups, L2 and L3 lookup)
2. (*)Outgoing packet passes filter for north/south traffic and then NAT flow
   is applied. Source address is modified according to tenant (connection
   tracking zone)
3. (*)Second NAT is applied in default connection tracking zone resulting
   external IP as a source address
4. Packet get routed to br-ex

Below is sample implementation of (*) marked steps in OVS flows. We use
NXC_NX_REG8 register to save tenant id between different connection tracking
zones and different flow tables:

::

  Egress direction phase #1: ( table 15 - Egress NAT traffic )
  VM originated packet passed tenant specific zone connection tracking,
  resulting following actions:
    2a) first NAT phase translation ( nat(src=182.0.0.1,hash) )
    2b) marking incoming VM port for return traffic  ( mark=VM1 )
    2c) load OVS register to refer to correct tenant ID and pass execution to
        a new table 16 (tenant NAT)

    table=15, in_port=VM1, ct_zone=tenant1, ct_state=+trk,
        actions=ct(commit,nat(src=182.0.0.1,hash), mark=VM1,
              load:tenant1->NXM_NX_REG8[]), resubmit(, 16)


  Egress direction phase #2: ( table 16 - Egress tenant NAT traffic )
  Tenant originated traffic passed default zone connection tracking,
  resulting following actions:
    3a) connection get mark with tenant ID
    3b) packet passes tenant NAT to external IP address 172.24.4.2
    3c) packet is routed to patch-ex port towards external bridge
       (br-int) via table 66

    table=16, ct_zone=default, ct_state=+trk,
        actions=ct(commit,nat(src=172.24.4.2,hash), mark=NSM_NX_REG8),
        resubmit(,66)


  Table 15 has one flow per locally deployed VM
  Table 16 may have single flow for all tenants due to saved tenant id

Preliminary implementation may use single connection tracking table


References
==========

https://bugs.launchpad.net/neutron/+bug/1639566
