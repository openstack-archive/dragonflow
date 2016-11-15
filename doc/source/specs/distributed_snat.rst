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
User reserves a single external IP address (from a limited pre-allocated
pool), which is used to masquerade multiple VMs of that same user
(therefore, sharing the same external IP).

With the "Distributed SNAT" solution, in contrast, the User reserves an
external IP address (from a limited pre-allocated pool) for every [Compute
Node, router] pair. This way north-south traffic of every VM will be routed out
locally via with external IP  of hosting Compute node

The main advantage of "Distributed SNAT" is the distribution of the NAT/PAT
function to the Compute Nodes, bypassing the Network Node.

The requirement of having dedicated Network node will be more flimsy with
"Distributed SNAT" probably apart from VPNaaS deployment


Problem Description
===================

Currently, when the User wants to allow multiple VMs to access external
networks (e.g. internet), she can either assign a floating IP to each VM
(DNAT), or assign just one floating IP to the router that she uses as a
default gateway for all the VMs (SNAT).

The downside of DNAT is that the number of external IP addresses is very
limited, and therefore it requires that the User either "switch"
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

When the Compute Node can route outbound traffic, VMs hosted on it do
not need to be routed through the Network Node. Instead, they will be
routed locally from the Compute Node.

In order to achieve dragonflow pipeline flow change for north-south traffic
new dragon flow application is required.

"Distributed SNAT" should be reflected in Neutron database, as it affects
router ports configuration and should be persistent. This model requires
definition of separate neutron port per pair of (Computer node, router).

In this proposal the router gateway port shall have a separate IP/MAC
address per Compute Node.

To enable the behavior change in this proposal, the Admin shall define
some configuration parameters (listed in the Configuration section
below). Neutron API is not a subject of change due to automated local
gateway port add/delete operations according to provided configuration
switch


Setup
=====

New Dragonflow application should handle north-south traffic on each Compute
Node.

Dragonflow controller creates br-ex bridge at every compute node and register
itself as the controller for this bridge.

When "Distributed SNAT" is enabled neutron server assigns external IP from
predefined pool to br-ex. New neutron ports are updated in neutron database.
Port type for such created neutron ports should be a new type:
'local-gateway-port'. SNAT dragonflow application is enabled

When "Distributed SNAT" is disabled all neutron ports with type:
'local-gateway-port' are deleted from neutron database. SNAT dragonflow
application is disabled. Legacy centralized SNAT model is enforced

Dragon flow controller should have proper installed rules priorities to
prioritize DNAT over SNAT

Flow
====

This section describe all the handling in the pipeline for north-south
traffic.

NAT translation can take place natively in OVS that supports NAT feature
starting from version 2.6.x or in terms of Netfilter rule in separate linux
namespace.

OVS native NAT support provide a more clean implementation.

Netfilter in linux namespace provide an alternative implementation where
NAT translation is enforced and traffic is routed further using native OVS
flows (dragonflow pipline)

When DNAT is defined DNAT rule have precedence over SNAT.

Ingress
-------

- Incoming traffic arrives to br-ex bridge.
- SNAT dragonflow flow application starts the pipeline
- Traffic passes netfilter NAT rule/dedicated OVS NAT flow
- Traffic passes to br-int bridge
- Configured dragonflow pipeline is applied

Egress
------

- Configured dragonflow pipeline is applied on br-int bridge
- Outgoing traffic passes filter for north-south traffic first and then routed
  towards br-ex bridge
- SNAT dragonflow flow application finishes the pipeline
- Traffic passes netflter NAT rule/dedicated OVS NAT flow

Configuration
=============

'enable-local-nat' - a boolean value that enables/disables automated IP
address acquiring for every Compute node. This setting should be part of
router configuration structure. Existing 'enable-snat' with value 'false'
setting will effectively limit 'enable-local-snat' to prevent ambiguity.


References
==========
Diagrams explaining the steps will be added
