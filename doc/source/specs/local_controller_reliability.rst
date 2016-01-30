This work is licensed under a Creative Commons Attribution 3.0 Unsuported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

================================
Local Controller Reliability
================================


Problem Description
================================

OVS 2.4 default to reset up flows when it lose connection with controller.
That means both restart of local controller and OVS will delete flows,
result in a disruption in network traffic.

The goal of this design is to describe how to keep the normal function of
Dragonflow if these exceptions occurred. The types of exception include but not
limited to the following:
Local controller restart
OVS restart
Residual flows
Missing flows


Proposed Change
=================


Solution to local controller restart
---------------------------------------
When local controller restarts OVS drops all existing flows. This break network
traffic until flows are re-created.

The solution add an ability to drop only old flows. controller_uuid_stamp is
added for local controller. This controller_uuid_stamp is set as cookie for
flows and then flows with stale cookies are deleted during cleanup.
The detail is:

1. Change the fail mode to secure, with this setting, OVS won't delete flows
when it lose connection with local controller.
2. Update flow cookie with new controller_uuid_stamp which is set when local
controller initialization, update flows with new cookie, retrieve all flows from
OVS, delete flows with stale cookies.

It should be noted that the controller_uuid_stamp cookie must be added for
add-flow and mod-flow.

Since cookie is used by some apps for smart deletion, so we should share the
cookie with those apps. I think we could divide 64-bit cookie into several
parts, each part is used for a specified purpose. e.g. we could use the least
significant part for this solution, the cookie_mask should be 0xf, while apps
could use the left 60-bits to do smart deletion.


+------------------+          +------------------+          +------------------+
|                  |          |                  |          |                  |
|        OVS       |          |    Dragonflow    |          |    CentralDB     |
|                  |          |                  |          |                  |
+---------+--------+          +---------+--------+          +---------+--------+
          |                             |                             |
          |   set fail mode to secure   |                             |
          | <---------------------------+                             |
          |                             |                             |
          |                             +-----+                       |
          |                             |     |restart                |
          |                             |     |                       |
          |                             +-----+                       |
          |                             |                             |
          |    notify all ports         |                             |
          +---------------------------> |     get ports' detail info  |
          |                             +---------------------------> |
          |                             |                             |
          |                             |     return  ports' info     |
          |                             | <---------------------------+
          |                             |                             |
          |   add flows with new cookie |                             |
          | <---------------------------+                             |
          |                             |                             |
          |                             |                             |
          |      get all flows          |                             |
          | <---------------------------+                             |
          |       return                |                             |
          +---------------------------> |                             |
          |                             |                             |
          |  delete flows with stale cookie                           |
          | <---------------------------|                             |
          |                             |                             |
          |                             |                             |
          +                             +                             +


Solution to OVS restart
--------------------------
OVS restart will delete all flows and interrupt the traffic.
After startup, OVS will reconnect with controller to setup new flows.

+------------------+          +------------------+          +------------------+
|                  |          |                  |          |                  |
|        OVS       |          |    Dragonflow    |          |    CentralDB     |
|                  |          |                  |          |                  |
+------------------+          +---------+--------+          +---------+--------+
          +----+                        |                             |
          |    |restart                 |                             |
          |    |                        |                             |
          +----+                        |                             |
          |                             |                             |
          |   notify all ports          |                             |
          +---------------------------> |                             |
          |                             |    get ports' detail info   |
          |                             +---------------------------> |
          |                             |                             |
          |                             |    return  ports' info      |
          |                             +<--------------------------- |
          |                             |                             |
          |   create bridges if needed  |                             |
          | <---------------------------+                             |
          |                             |                             |
          |                             |                             |
          |   add flows with new cookie |                             |
          | <---------------------------+                             |
          |                             |                             |
          |                             |                             |
          +                             +                             +


Solution to residual flows
----------------------------
Residual flows means flows which don't take effect any more but stay in flow
table. Backward incompatible upgrade and incorrect implementation may generate
this kind of flows. The residual flows may not affect the forwarding but it will
occupy flow table space and add difficulty for maintenance.

The methods to manage this issue:
Delete all flows before adding new flows
We could reuse the solution for 'OVS restart', trigger local controller to
re-flush flows then delete the flows with old cookie.

Pros
-----
It's easy to implement because we could reuse the solution for 'OVS restart'

Cons
-----
It's not efficient because we need to regenerate all the flows again.

This method is suited for the residual flows caused by the
'backward incompatible upgrade'.


Solution to missing flows
----------------------------------
When there are missing flows, OVS cannot forward the packet by itself, it will
forward the packet to local controller. For example, in the context of DVR
forwarding, if no corresponding host route flow to destination, OVS will forward
the packet to local controller according to the network flow. Upon receive the
packet, local controller forward the packet, regenerate host flow and flush it
to OVS. We don't plan to discuss it in more detail here and it will be processed
by the specific application of Dragonflow.

References
==========
http://www.openvswitch.org/support/dist-docs-2.4/ovs-vswitchd.8.pdf
http://www.openvswitch.org/support/dist-docs-2.4/ovsdb-server.1.pdf
https://bugs.launchpad.net/mos/+bug/1480292
https://bugs.launchpad.net/openstack-manuals/+bug/1487250
https://www.kernel.org/doc/Documentation/networking/openvswitch.txt