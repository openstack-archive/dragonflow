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

Currently Dragonflow uses only one OVS bride to model its entire pipeline, for
this feature we introduce another bridge (br-ex) to model public external network
as currently done in the network node.

Its important to note that this is done only for modeling and in later versions
its logic can be folded into one bridge.
A performance penalty is not expected as patch-ports are not really installed
in the kernel cache.

Setup
-----
Dragonflow controller creates br-ex bridge at every compute node and register
it self as the controller for this bridge.
The Dragonflow controller needs to distinguish between the two bridges and
each application must install its flows to the correct bridge.

The user needs to configure and define the external network and add its port
to br-ex.
Dragonflow needs to keep a mapping of external networks to bridges, as
potentially more then one external network can be configured.
(In this case each external network will have its own br-ex bridge and
Dragonflow controller must have the correct mappings internally)

Configuration - Floating IP Added
---------------------------------
Floating IP is configured in the Neutron DB and Dragonflow plugin map this
configuration to Dragonflow's DB model and populate floating ip table.

Each controller must detect if the floating IP is assigned to a local port
and in the case that it is, install the relevant flows for both ingress and
egress as described below.

Currently Dragonflow uses Neutrons L3-Agent for centralized SNAT and DNAT
in the network node.
Since Dragonflow doesnt yet support Distributed SNAT, the l3-agent is
still needed for SNAT.
We need to make sure that floating IP configuration is not being applied
by the L3-agent.
Applying it in the network node FIP namespace might introduce conflicts in
resolving the IP. (Two compute nodes replying for ARP of the FIP address)
This feature might require code changes to the l3-agent.

Ingress
-------
This section describe all the handling in the pipeline for traffic destined
to the floating IP address coming from the external network.

1) Add ARP responders in BR-EX for every local FIP, reply with FIP port
   MAC address.
   (This can be added in a designated table for ARP traffic while table 0
   matches on ARP)
   Match only on traffic coming from external network.

2) Add NAT flow converting from the floating ip destination to the VM private
   IP destination and change the destination MAC to the VM MAC
   (current MAC address should be the same as the floating ip port)
   SRC MAC also needs to be changed to the router gateway MAC.
   Match only on traffic coming from external network.

   Before this point FWaaS must be applied, we can either:

   - Add this logic in flows in Dragonflow pipeline

   - Direct traffic to a local FW entity port.

   - Receive FW services from external appliance, in that case the FWaaS
     should have already been applied before the pakcet arrived at the
     compute node.

   A special table for Ingress/Egress processing of logical router
   services can be introduced in Dragonflow pipeline.
   The Ingress side of the table (traffic coming from external network)
   is added after the classification table (table 0) for every in_port
   that represent a router port (patch_ports in our case).
   The Egress side is done just after the L3 lookup table.
   A different detailed spec must be introduce to define this, this spec
   however has no conflicts with such possible design.

3) For every floating IP a patch port is added between br-ex and br-int
   after the NAT conversion (IP and MAC) send the packet to the correct
   patch-port.


4) On br-int, add a matching flow on in_port (for the patch port),
   classify it with the same network as the destination VM (the VM
   that this floating IP belongs too) and continue the same regular
   pipeline.
   reg6 value is set with the floating IP port unique number for ingress
   security rules to be applied.

   The L2 lookup stage in the pipeline should match on the
   destination VM MAC and send it to the egress security table and
   then dispatch to the correct port (the VM port).

Egress
------
This section describe all the handling in the pipeline for traffic that
originates from the VM (which has a floating IP) and destined to the
external network.

1) Packet traverse the pipeline in the same manner until it reaches the L3
   lookup table.
   It is important to note that we already have ARP responders for the
   logical router default gw port, so the packet destination MAC is the
   router gateway port MAC.

2) The L3 table recognize no match for east-west traffic, meaning the dst
   IP is a north-south address. (external network and not a private address).
   packet is sent to a new table added to the pipeline called
   "Egress NAT Processing"

3) In the new table, match on the source in_port, if this is from a VM
   that has floating IP configured, change reg7 value to point to the
   patch port number of this floating IP.
   (At this point reg7 should have the value of the router port unique key)

4) At the egress table (after egress security rules) add flow to send the
   packet to br-ex using the correct patch port.
   (** We can avoid the extra steps and send the packet to the patch
   port in step 3, however doing it this way also includes egress security
   and introduce better modeling)

5) At br-ex match flow according to patch-port in_port and apply the NAT
   rule.
   Change src ip from the VM private ip to the floating ip.
   Change src mac to the floating IP mac.

   Same as the Ingress, FWaaS integration point is at this step, all the
   previously mentioned options can be applied.

6) At this point we also need to change the dst MAC of the packet to the
   external network gateway MAC, this information is currently not
   supplied by Neutron.
   The action needed is to send an ARP request for the gateway IP,
   however such mechanism is not currently present in OVS.
   We can have the MAC address configured at first step and then introduce
   a mechanism that ARP the gateway and updates flows accordingly.
   (This process needs to run periodically as the MAC can change)

References
==========
Diagrams explaining the steps will be added
