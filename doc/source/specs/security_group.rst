..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==================
Security Group
==================

https://blueprints.launchpad.net/dragonflow/+spec/security-group-dragonflow-driver
his blueprint describe how to implement Security Group in Dragonflow.

Problem Description
===================
Neutron use iptables to implement security group in current community solution.
Because connect tracking is not supported by ovs, a linux bridge is inserted
between VM and ovs bridge. However, it introduces unnecessary overhead and
latency for traffic forwarding.

As connection tracking is supported in ovs v2.4.0 now, seurity group iptables
rules can be translated into openflow tables and installed in ovs bridge to
implement traffic security control.

This blueprint intends to support security group directly in ovs bridge only
using flow tables without iptables and corresponding linux bridges.
It can improve forwarding efficiency due to packets only go through the
network stack once. The traffic in iptables solution needs to go through the
network stack twice (including linux bridge and ovs bridge).

Proposed Change
===============
The following flow describe the changes needed in Dragonflow pipeline in order
to support security groups. Dragonflow controller will create security group
flow  tables for Dragonflow pipeline to make security group functional.

Setup
------
For blueprint solution, nova should not create linux bridge and should plug port
directly into integrity bridge.

the user needs to configure security groups and rules, and bind security group
to the port.

Configuration - Security Group Added
----------------------------------
Security Group is configured in the Neutron DB and Dragonflow plugin map this
configuration to Dragonflow's DB model and populate security group table.
Each controller must detect if the Security Group is assigned to a local port or
remote port that has corresponding flows in local node and in the case that it is,
delete and  updates the relevant flows for security tables as described below.

Security Group Table manipulation
-------
This section describe all the handling in the pipeline for security group.
1) add a new table which implements security group between service traffic table
   and L2 lookup table.

2) add default packin controller flow which means all flows defaults to
   controller

3) install "pass" or "drop" flow reactively according to the security rules.
   If the rule permits the packet, install a flow to let it goto the L2 lookup
   table; otherwise, drop the packet. This flow's priority is higher than the
   default flow, so the same packet will pack-in controller only once. This
   flow uses src ip and dst ip to match the corresponding egress rules of local
   port and ingress rules of remote port. Notice that dropping packet always
   happens in the sender side to avoid unnecessary wasting of band.

4) local controller only caches the security group rules of local port. When local
   permits the packet to pass, local controller also look up the rules of remote
   port according to the dst ip from the distributed db(the local controller
   does only cache local and related remote port's security gruop rules)

5) When security group rule associates with a port has been updated. The local
   controller must delete the corresponding "pass" and "drop" flows in the security
   group table matching the keys of src ip or dist ip. This means the local controller
   not only needs to care security group rules of local port but also remote port.
   So when the next packet comes in, it will be packeted in the controller again
   and the controller will calculate and install flows according to new security group
   rules of both local port and remote port.

References
==========
https://github.com/justinpettit/ovs/tree/conntrack
https://lwn.net/Articles/652967/
http://openvswitch.org/support/ovscon2014/17/1030-conntrack_nat.pdf
