=================
Distributed SNAT
=================

Scope
=====

This spec focus on a new, additional SNAT implementation to Neutron (which
we will henceforth refer to as "Distributed SNAT") that trades off some
functionality in favor of scale, performance and ease of use (all
highlighted in "Problem Description" section).

All references to IP in this spec refer to IPv4 addressing scheme (IPv6 is
out of scope for this spec).

The main functionality difference between the Neutron reference
implementation of SNAT and "Distributed SNAT", is that with Neutron SNAT the
cloud admin reserves a single external IP address (from a limited
pre-allocated pool), which is used to masquerade multiple VMs of that same
tenant therefore, sharing the same external IP.

With the "Distributed SNAT" solution, in contrast, the cloud admin reserves an
external IP address (from a limited pre-allocated pool) for every [Compute
Node, tenant gateway] pair/Compute node (see Flow section for implementation
alternatives). This way north-south traffic of every VM will be routed out
locally via external IP of hosting Compute node

The main advantage of "Distributed SNAT" is the distribution of the NAT/PAT
function to the Compute Nodes, bypassing the Network Node.

The requirement of having dedicated Network node will be more flimsy with
"Distributed SNAT" probably apart from VPNaaS deployment


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
it as default gateway will go through the Network node that hosts the router,
effectively creating a network bottleneck and single point of failure for
multiple VMs.


Proposed Change
===============

This spec outlines an additional SNAT model that places the NAT/PAT on
each Compute Node. In order for this design to work in a real world
deployment, the underlying networking infrastructure needs to allow Compute
Nodes to access the external network (e.g. WWW).

Such SNAT model is changing the concept of legacy router where single gateway
port is present. Even neutron DVR implementation follows legacy concept in
terms of single gateway port and same internal router port (in terms of MAC/IP
addressing) copied across compute nodes. However this model redefines single
gateway port concept actively defining more then one gateway port on single
distributed router.

When the Compute Node can route outbound traffic, VMs hosted on it do
not need to be routed through the Network Node. Instead, they will be
routed locally from the Compute Node.

In order to achieve Dragonflow pipeline flow change for north-south traffic
new dragonflow application is required.

"Distributed SNAT" should be reflected in Neutron database, as it affects
router ports configuration and should be persistent. This model requires
definition of separate neutron port per Compute node or per pair of
[Compute node, tenant gateway] (see Flow section for implementation
alternatives).

From tenant point of view external network is usually accessed via single
gateway (port on specific router). This means definition terms of SNAT
per [Compute node, tenant gateway] pair and [Compute node, tenant] pair are
pretty equivalent in most deployments.

In this proposal the router gateway port shall have a separate IP/MAC
address per Compute Node.

To enable the behavior change in this proposal, the Admin shall define
some configuration parameters (listed in the Configuration section
below). Neutron API is not a subject of change due to automated local
gateway port add/delete operations according to provided configuration
switch

In order to handle high availability Dragonflow controller may monitor
external connectivity periodically and perform a fallback to Neutron SNAT.


Setup
=====

New Dragonflow application should handle north-south traffic on each Compute
Node. East-west traffic between VMs of different tenants deployed on different
compute nodes falls into this category as well. Application should handle
(tenant) gateway add/remove events and install/uninstall appropiate NAT flows
as described in Ingress/Egress sections below.

Dragonflow controller creates br-ex bridge at every compute node and register
itself as the controller for this bridge.

When "Distributed SNAT" is enabled, appropriate service assigns external IP
from predefined pool to br-ex of each compute node. This change adds router
gateway ports to neutron database. New ports should have type: 
'df-local-gateway-port'.

When "Distributed SNAT" is disabled, implementation should remove all neutron
ports with type: 'df-local-gateway-port' from neutron database. SNAT traffic
will follow legacy centralized SNAT model.

Dragonflow controller should have proper installed rules priorities to
prioritize DNAT over "Disributed SNAT"

Flow
====

This section describe all the handling in the pipeline for north-south
traffic.

NAT translation can take place natively in OVS that supports NAT feature
starting from version 2.6.x.

OVS native NAT support allows a clean SDN implementation.

Alternative #1 - External IP address per [Compute node, tenant gateway] pair
Below diagram outlines single compute node:


::

       +  Tenant 1       +  Tenant 1         +  Tenant 2
       |  10.0.0.1       |  10.0.0.2         |  10.0.0.1
       |                 |                   |
  +----|-----------------|-------------------|---------------+
  |    \--------\ /------/                   |      br-int   |
  +--------------v---------------------------v---------------+
                 | NAT:                      |  NAT
    public net   | 172.24.4.2                |  172.24.4.3
  +--------------|---------------------------|---------------+
  |              |                           |      br-ex    |
  +--------------|---------------------------|---------------+
                 |                           |
                 v                           v

Different external IP address per tenant gateway is required to distinguish
between possible private networks address overlapping across multiple tenants.
Single extenal IP may result hash ambiguity in NAT feature on returning
traffic.


Alternative #2 - Single external IP per compute node
Such solution requires intermidate NAT to shared private network and then NAT
to public external IP.

Below diagram outlines single compute node:


::

        +  Tenant 1       +  Tenant 1         +  Tenant 2
        |  10.0.0.1       |  10.0.0.2         |  10.0.0.1
        |                 |                   |
   +----|-----------------|-------------------|---------------+
   |    \--------\ /------/                   |      br-int   |
   +--------------v---------------------------v---------------+
                  | NAT:                      |  NAT
    shared private| 182.0.0.1                 |  182.0.0.2
   +--------------v---------------------------v---------------+
   |              \-------------\ /-----------/      br-ex    |
   +-----------------------------v----------------------------+
                                 |  NAT
                       public    |  172.24.4.2
                                 v

Shared private network serves as an intermidiate step to translate single
external IP to private IP of specfic tenant. Shared private network requires
neutron database update.

Both alternatives require management of network adress pool and
acquire address when new tenant gateway is introduced. While alternative #2 is more
efficient in terms of external IP address use it may require extra compute
power for connection tracking and extra NAT.

When DNAT is defined, DNAT rule have precedence over "Distributed SNAT".

Ingress (alternative #2)
------------------------

- Incoming traffic arrives to br-ex bridge.
- Packet passes reverse NAT to shared private network and routed to br-int
- Tenant connection zone is identified
- Packet pass another connection tracking (specific zone conntrack table)
- Packet passes another reverse NAT and routed to regular dragonflow pipeline
- Regular dragonflow pipeline is applied (security groups)

Egress (alternative #2)
-----------------------

- Configured dragonflow pipeline is applied on br-int bridge (conntrack,
  security groups, L2 and L3 lookup)
- Outgoing packet passes filter for north-south traffic and then NAT flow is
  applied. Source address is modified according to tenant (connection tracking
  zone)
- Packet get routed to br-ex
- Second NAT is applied in default zone resulting external IP as a source
  address

Preliminary implementation may use single connection tracking table (single
zone)

Configuration
=============

'enable-local-nat' - a boolean value that enables/disables automated IP
address acquiring for every Compute node. This setting should be part of
router configuration structure. Existing 'enable-snat' with value 'false'
setting will effectively limit 'enable-local-snat' to prevent ambiguity.

Alternative option to enable/disable "Distributed SNAT" feature is a
presense of SNATApp application in the application list of Dragonflow
configuration file.


