..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

================
Distributed DNAT
================

https://blueprints.launchpad.net/dragonflow/+spec/fip-distribution

This blueprint describe how to implement distributed DNAT (Floating IP)
in Dragonflow.

Problem Description
===================
Allow for FIP distribution for compute host with external network
gateway port.

In the current implementation FloatingIP (DNAT) translation done at
the Network Node in a centralize way creating extra latency,
bottleneck and introducing SPOF.

This blueprint intend to support FIP traffic to be sent directly to the
external network without going through the network node while preserving the
centralize solution for Compute host that are not connected to the external
network directly.

For network segment that need direct access to the public network this could
improve scalability and remove the network node bottleneck and SPOF.
Deployment of the web tier can be done using the availability zone to
distinguish the compute hosts with additional external network port.
(New nova filter can be introduced later to achieve this, similar to
SRIOV PciPassthroughFilter or ServerGroupAffinityFilter)

Proposed Change
===============
The following flow describe the changes needed in Dragonflow pipeline in order
to support distributed DNAT.

Dragonflow will mark floating ports created one per each floating IP entity as
either local or remote (or unbound) depending on the binding of floating IP's
target port.

By marking the floating port as bound, all our other apps will treat it as any
other port, creating all relevant flows.

Configuration - Floating IP Added
---------------------------------
Floating IP is configured in the Neutron DB and Dragonflow plugin map this
configuration to Dragonflow's DB model and populate floating ip table.

Each controller must detect if the floating IP is assigned to a local or remote
port and in the case that it is, mark the floating port accordingly, and
install the relevant flows for both ingress and egress as described below.

Ingress
-------
This section describe all the handling in the pipeline for traffic destined
to the floating IP address coming from the external network.

1) Since floating port was marked local:

  * L2 app creates flows in L2 lookup table that match network key / dest MAC
    address to port key
  * Provider/tunnelling apps create flows to make the floating network
    available on the integration bridge.

2) Translation flows are added for all packets bound for floating port.
   Destination IP and MAC adderesses are updated to ones of the target port.
   Source MAC is changed to that of the relevant router interface.
   TTL is decremented.

3) Packet is forwarded to L2 lookup table for further processing. FWaaS should
   happen before this step when added.

Egress
------
This section describe all the handling in the pipeline for traffic that
originates from the VM (which has a floating IP) and destined to the
external network.

1) Packet traverse the pipeline in the same manner until it reaches the L3
   lookup table.

2) The L3 table recognize no match for east-west traffic, meaning the dst
   IP is a north-south address. (external network and not a private address).
   packet is sent to a new table added to the pipeline called
   "Egress NAT Processing"

3) Packet will match on source port, fixed IP of the floating IP entity,
   dest MAC and router key, and replace packet's network key, source MAC,
   source IP and decrement TTL. Them packet will be forwarded to L2 for further
   lookup in the floating network.
