..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

========================
Distribute Load Balancer
========================

Include the URL of your launchpad RFE:

To be added.

This blueprint describe how to implement distributed load balancer in Dragonflow.


Problem Description
===================
Load Balancer traffic can be handle in distributed mode.

Centralized load balancer have a weak point which is All load balancer
traffics need go to centralized load balancer which will be bottleneck,
and Centralized load balancer will introduce SPOF.

This blueprint intend to support load balancer traffic to be handle in
compute host without go to centralized load balancer node.

Proposed Change
===============

The following flow describe the changes needed in Dragonflow control
plane and data plane in order to support distributed load balancer.

The spec will follow LBaaS V2 API, since LBaaS V1 API is deprecated.

Control Plane
-------------

Configuration - Listener added

Configuration - Load balancer added

Configuration - Member added

Configuration - Pool added

Configuration - Health Monitor added

Data Plane
----------

In order to implement load balancer functionality, this spec proposes
adding a new table called load balancer table in which all load balancer
flows will be built.

All traffics destined to some VIP are load balancer ones, it needs to
add a classified flow in l2_lookup table to let all load balancer traffic
goto load balancer table.

Ingress
~~~~~~~

1. Add ARP responders for every VIPS, reply with VIP port MAC
   address. (This can be added in a designated table for ARP traffic while
   table 0 matches on ARP) Match only on traffic coming from VM,since this
   spec only will be limit in east west load balancer use cases.

2. In load balancer table, it uses group instruction with select mode
   to implement load balance algorithm.

3. There are three use case.

   :Case 1:
     Client and vip are in the same subnet,but member is not.

     1.1. The L2 lookup stage in the pipeline should match on the
          destination VIP MAC and send it to the load balancer table.
     1.2. In load balancer table, match metadata and vip, action is to
          execute load balance algorithm to select one member, then change
          dst ip to member's ip address and change dst mac to member's mac
          address, then load member's port key to reg7, lastly send to
          egress table.

   :Case 2:
     vip and member are in the same subnet, but client is not. since
     client and vip are not in the same subnet, lb traffic will be
     forwarded by distributed router to vip's subnet.

     2.1. The ingress dispatched table, should match on the destination VIP MAC
          and send it to the load balancer table.
     2.2. In load balancer table, match metadata and vip, action is to execute
          load balance algorithm to select one member, then change dst ip to
          member's ip address and change dst mac to member's mac address, then
          load member's port key to reg7, lastly send to egress table.

   :Case 3:
     vip,client and member all are in three different subnets.

     3.1. The ingress dispatched table, should match on the destination VIP MAC
          and send it to the load balancer table.

     3.2. In load balancer table, match metadata and vip, action is to execute
          load balance algorithm to select one member, then change dst ip to
          member's ip address and change dst mac to member's mac address, then
          load member's port key to reg7, lastly send to egress table.

   :Case 4:
     vip,client and member all are in the same subnet.

     4.1. The L2 lookup stage in the pipeline should match on the destination
          VIP MAC and send it to the load balancer table.

     4.2. In load balancer table, match metadata and vip, action is to execute
          load balance algorithm to select one member, then change dst ip to
          member's ip address and change dst mac to member's mac address, then
          load member's port key to reg7, lastly send to egress table.



Health Monitor
--------------

This spec proposes a distributed health monitor solution. It is composed
of health monitor app and member health's status stored DB. health monitor
app is dragonflow one which is located at every computer node. it is
responsible of checking the status of any member which is located in the
same computer node as health monitor. The checking result will be stored
into DB, then this information will be propagated to health monitor app
in other compute node.

For a load balancer instance, health monitor app will send health monitor
request by openflow packet_out message to all its members in the same
compute node as health monitor app. health monitor response traffic need
to be transfer to health monitor app to further handling.

It is necessary to distinguish the health monitor return traffic and the
other traffic sent from member to vip. it will introduce a new register
(regX) to identify this kind of traffic.

The L2 lookup stage and ingress dispatched stage in the pipeline should
match on destination mac with vip mac and match on regX, then send to
controller.

There should have a identification to let health monitor app know this
health monitor traffic belongs to which load balancer

References
==========

[1] http://developer.openstack.org/api-ref/networking/v2/?expanded=create-load-balancer-detail#lbaas-2-0-stable

[2] http://docs.openstack.org/newton/networking-guide/config-lbaas.html
