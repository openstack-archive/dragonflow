=================
Distributed SNAT
=================

Scope
=====

This spec focuses on a new, additional SNAT implementation to DragonFlow (which
we will henceforth refer to as "Distributed SNAT") that trades off some
functionality in favor of scale, performance and ease of use (all
highlighted in "Problem Description" section).

All references to IP in this spec refer to IPv4 addressing scheme (IPv6 is
out of scope for this spec).

The main functionality difference between the legacy DragonFlow
implementation of SNAT and "Distributed SNAT", is that with legacy
DragonFlow SNAT the cloud admin reserves a single external IP address
(from a limited pre-allocated pool), which is used to masquerade multiple
virtual hosts that egress via the same router port, sharing the same external
IP.

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
DragonFlow plugin update. Therefore "Distributed SNAT" should not be reflected
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


[2] External IP address per [compute node, tenant gateway] pair

Pros:
    - generic solution similar to Neutron in terms of tenants separation
    - blacklisting single tenant will not affect others on same compute host
Cons:
    - more complex implementation in terms of external IPs management
    - solution consumes #[tenants * compute hosts] external IPs

Note: excessive external IPs consumption in solution [2] can be further reduced
by provider router translation that should lead to single IP per tenant. Such
scheme is out of scope of this spec.


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

This section describes all the handling in the pipeline for north/south
traffic and provides design details for solution alternative [1].

NAT translation can take place natively in OVS that supports NAT feature
starting from version 2.6.x.

OVS native NAT support allows to untie need for linux namespaces required by
Neutron SNAT implementation.

Single SNAT problem and workaround
----------------------------------
"Distributed SNAT" results a single external IP per compute node. We
want to achieve this with a single address translation. However general
deployment scenario allows for address collision, e.g. where different
tenant have same subnet range for a private subnet, which leave us a
tangible possibility of exactly same 4-tuple (IP1, port1, IP2, port2)
produced by different tenant VMs. 4-tuple collision makes it impossible
to pass single zone connection tracking correctly.

To avoid this address overlap issue, we will encode the source's identifier
as the source IP (Similar to the solution used in the metadata service).

Specifically, we will store the original source IP in the connection
tracking's metadata, e.g. ct_mark field. We will store the source's identifier
(available in reg6) in the source IP, and then we will pass it through NAT.

On the return packet, the un-NATted packet will have the virtual host's
identifier in the destination address. We will move that to reg7, and
set the destination address to the value in ct_mark (which we stored on
egress).

OVS's connection tracking requires a zone to be specified, to differentiate
SNAT traffic from east-west traffic. A constant value will be used for the
zone, either selected statically, or dynamically to avoid collision.

Below diagram outlines single compute node and address manipulation:
Source IP address - 32-bit unsigned integer translated to host unique 32-bit
unsigned integer.

::

        +  Tenant 1       +  Tenant 1         +  Tenant 2
        |  10.0.0.1       |  10.0.0.2         |  10.0.0.1
        |                 |                   |
   +----|-----------------|-------------------|---------------+
   |    \--------\ /------/                   |      br-int   |
   |              v                           v               |
   | 10.0.0.1->101| 10.0.0.2-> 102            | 10.0.0.2->103 |
   |              |                           |               |
   |              v                           v               |
   |              \-------------\ /-----------/               |
   +-----------------------------v----------------------------+
                                 |  NAT
                     public net  |  172.24.4.2
   +-----------------------------|----------------------------+
   |                             |                    br-ex   |
   +-----------------------------|----------------------------+
                                 v


Data model impact
-----------------
No change


Egress
------

1. SNAT flows will be applied after L3 lookup, when it is decided that the
   packet is north-south communication, and not east-west.
2. (*)Outgoing packet passes NAT flow. VM port is used as a source IP and
   source IP is stored in connection tracking entry
3. Packet get routed to br-ex

Below is sample implementation of (*) marked step in OVS flows.

::

   table=20, priority=100,ip,actions=move:OXM_NX_IP_SRC->NXM_NX_REG8[],
      move:NXM_REG6[]->OXM_NX_IP_SRC[],
      actions=resubmit(,30)

   table=30, priority=50,ip actions=ct(commit,table=31,
      zone=65000,nat(src=172.24.4.2),
      exec(move:NXM_NX_REG8[0..31]->NXM_NX_CT_MARK[])

  table=31, priority=50,ip
    actions=mod_dl_src:91:92:93:94:95:96,mod_dl_dst:42:b9:63:88:a0:48,
    resubmit(,66)

Ingress
-------

1. Incoming traffic arrives to br-ex bridge.
2. (*)Packet is routed to br-int and passes reverse NAT.
3. (*)Destination IP address is moved to reg7 (It was set to the destination's
   ID on egress)
4. (*)Destination IP address is set to ct_mark
5. The packet is passed to table 78 to be dispatched directly to the VM.

Below is sample implementation of (*) marked step in OVS flows.

::

  table=0, priority=5, ip, actions=resubmit(,15)

  -- NAT conn. track phase -----------
  table=15, priority=50,ip actions=ct(table=16,nat,zone=65000)

  -- NAT actions phase ---------------
  table=16, priority=50,ip
     actions=mod_dl_src:91:92:93:94:95:96,mod_dl_dst:fa:16:3e:95:bf:e9,
     move:OXM_NX_IP_DST[]->NXM_NX_REG7[],
     move:NXM_NX_CT_MARK[]->OXM_NX_IP_DST[0..31],resubmit(,78)


Compute node local configuration
--------------------------------
- external_host_ip        - static external IP to be used by "Distributed SNAT"
                            This value is global, and is also used by e.g. BGP


References
==========

https://bugs.launchpad.net/neutron/+bug/1639566
