..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=====================================
Support firewall as a service (FWaaS)
=====================================

Problem Description
===================

Firewall is a necessary functionality in cloud infrastructure. It can provide
a barrier between a trusted internal network and another external network.

Currently, Dragonflow supports security groups, which can supply filtering
based on whitelists. A firewall can provide more functionalities and more
granular for users, just as the OpenStack Neutron spec described：

https://specs.openstack.org/openstack/neutron-specs/specs/mitaka/fwaas-api-2.0.html

Scope
=====

Our goal is to support all the functionalities in the Neutron FwaaS v2 spec.
Given FwaaS v2 is still under development, a few features are not ready, this
spec only covers the basic firewall functionalities, including map the Neutron
FwaaS v2 data model to Dragonflow controller and apply the firewall rules to
router interfaces.

Address group, service group and applying firewall rules to VM ports, SFC ports
are not implemented in Neutron FwaaS v2 yet, so they will not be covered in
this spec.

Proposed Change
===============

The proposed change will add both a new firewall plugin and a new APP to
Dragonflow controller.

The firewall plugin
-------------------

The OpenStack Neutron FwaaS plugin manipulates the firewall data objects
and talks to Neutron agents via RPC. However, Dragonflow needs a
plugin can talk to NB DB and publish events to Dragonflow controllers.

So a new Dragonflow firewall service plugin will be added.

To leverage the firewall objects and logic Neutron FwaaS defined, the new
firewall plugin will inherit the Neutron firewall plugin and implement the
communication with NB DB, including publishing events. In this way, Dragonflow
firewall plugin can work both with Dragonflow local controller and other
Neutron agents via its parent class.

Firewall APP for Dragonflow controller
--------------------------------------

OpenStack Neutron FwaaS v2 introduces the concept of firewall group. The
firewall group is the association point for binding firewall policies and
Neutron ports. A firewall group contains an ingress policy, an egress policy
and a group of ports. The data model looks like:

::

                                     +----------------+      +---------------+
                                -----> Ingress Policy +----> + Firewall Rules|
                                |    +----------------+      +---------------+
                                |
                                |
 +-----------------+      +-----+---------+
 | Ports(VM/Router)+------> Firewall Group|
 +-----------------+      +-----+---------+
                                |
                                |
                                |   +---------------+    +---------------+
                                ----> Egress Policy +----> Firewall Rules|
                                    +---------------+    +---------------+

According to the data model, a firewall group port table and a firewall rule
table will be added to the Dragonflow ingress and egress pipelines.

To decouple ports and firewall rules, the firewall group port table only handle
ports that has been added to a firewall group, and the firewall rule table maps
the firewall rules to Openflow flow entries without caring adding/removing ports.
When a port is added or deleted from a firewall group, only the firewall group
port table is updated and the traffic from/to other ports in the firewall group
will not be affected during the updating.

Egress:

A unique key will be allocated for each firewall group from NB DB. If a packet
is sent to a router interface that has been add to a firewall group, then the
unique key of the firewall group will be loaded to REG4 and the packet will be
resubmitted to firewall rule table. Otherwise, the packet will be sent to
Egress Security Group table directly.

In the firewall rule table, the firewall rules in the firewall group specified
by REG4 are applied to the packet.

* If the action of the rule is allow, the flow will be resubmitted to Egress
  Security Group table

* If the action is drop, the flow will be dropped silently

* If the action is reject, the flow is dropped and an ICMP destination-
  unreachable packet is sent back. We will implement this by a packet-out event
  with a rate limiter.

In addition, the Egress Security Group commits the flow to conntrack and the
Egress Connection Tracking table handles flows according the state in
conntrack. So the firewall can reuse the conntrack state.

The pipeline looks like:

::

               +---------+    +-----------+                        +---------+
    +-----+    |         |    |           |                        |         |
    |     |    | Port    |    | Egress    | FW app is not loaded   | Egress  |
    | VM  +--> | Security+--> | Connection+----------------------->| Security|
    |     |    |         |    | Tracking  |                        | Group   |
    +-----+    |         |    |           |                        |         |
               +---------+    +-----------+                        +-----+---+
                                  |                                      ^
                                  |   +----------------+   Port not in   |
                                  |   | Egress router  |   any FW group  |
                                  ----> ports FW group |-------->--------|
                                      +----------------+                 |
                             load firewall   |                           |
                           group key to REG4 |                           |
                                      +------v---------+                 |
                                      |  Egress router |                 |
                                      |  FW rules      |-------->--------|
                                      +----------------+  rule Action=allow

Let's say we add a rule that drop all traffic from IP address 192.168.0.4,
and then add a rule to allow the traffic to IP address 192.168.1.10, at last
we add the rules to a policy, then we add the policy and a router port to a
firewall group, the flows look like:

::

 # firewall port table
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=-new+est-rel-inv+trk actions=resubmit(,9)
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=-new+rel-inv+trk actions=resubmit(,9)
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=+new+rel-inv+trk,ip actions=ct(commit,table=9,zone=NXM_NX_CT_ZONE[])
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=+inv+trk actions=drop

 cookie=0xXX, table=<FW EGRESS PORT>, priority=100,dl_dst=router_inf_mac,ct_state=+new-est-rel-inv+trk,ip
                actions=load:FwGroup-KEY->NXM_NX_REG4[], resubmit(,<FW INGRESS RULE>)

 # firewall rule table
 cookie=0xXX, table=<FW EGRESS RULE>, priority=10000, reg4=FwGroup-KEY,ip,nw_src=192.168.0.4 action=drop
 cookie=0xXX, table=<FW EGRESS RULE>, priority=9800, reg4=FwGroup,ip,nw_dst=192.168.1.10 action=resubmit(,<EGRESS SECURITY GROUP>)
 cookie=0xXX, table=<FW EGRESS RULE>, priority=1, actions=drop

The priority of the flow entry in firewall rule table is corresponding to the
order of firewall rules. The rules come first have the higher priority.

To support inserting firewall rules, we use a big number as the priority when
firewall group is created and leave a big gap between rules. For example, a rule
is inserted between rule1 with priority A and rule2 with priority B in an
existing firewall policy, the firewall APP will check if there is a number
between A and B available. If yes, install the flow with this number as the
priority; if no, re-organize the priorities of all the flows, and then reinstall
them.

Ingress:

It is similar to the Egress pipeline:

::

    +-----------+                           +---------+    +---------+
    |           |                           |         |    |         |    +-----+
    | Ingress   |                           | Ingress |    | Ingress |    |     |
    | Connection+---------------------------> Security+--->| Dispatch+--->| VM  |
    | Tracking  |                           | Group   |    |         |    |     |
    |           |                           |         |    |         |    +-----+
    +-----------+                           +---->----+    +---------+
          |                                      |
          |   +----------------+  Port not in    |
          |   | Ingress router |  any FW group   |
          ----> ports FW group |-------->--------|
              +----------------+                 |
     load firewall   |                           |
   group key to REG4 |                           |
              +------v---------+                 |
              | Ingress router |                 |
              | FW rules       |------->---------|
              +----------------+  rule Action=allow

::

 # firewall group table
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=-new+est-rel-inv+trk actions=resubmit(,9)
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=-new+rel-inv+trk actions=resubmit(,9)
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=+new+rel-inv+trk,ip actions=ct(commit,table=9,zone=NXM_NX_CT_ZONE[])
 cookie=0xXX, table=<FW EGRESS PORT>, priority=65534,ct_state=+inv+trk actions=drop

 cookie=0xXX, table=<FW INGRESS PORT>, priority=100,dl_src=router_inf_mac,ct_state=+new-est-rel-inv+trk,ip
                actions=load:GRP-KEY->NXM_NX_REG4[], resubmit(,<FW EGRESS RULE>)
 cookie=0xXX, table=<FW INGRESS PORT>, priority=1, actions=resubmit(,<Sec-Grp>)

 # rule table
 cookie=0xXX, table=<FW INGRESS RULE>, priority=10000, reg4=GRP-KEY,ip,nw_src=192.168.0.4 action=drop
 cookie=0xXX, table=<FW INGRESS RULE>, priority=1, actions=drop

NB Data Model Impact
--------------------

Three tables will be added to the Dragonflow Northbound DB, firewall group table,
firewall policy table, firewall rule table. Similar to the Neutron FwaaS data
model, firewall group tables contains ingress firewall policy
and egress firewall policy, as well a list of ports. Each firewall policy
tables contains a list of firewall rules in the policy.

To make it easy to update the firewall rules, each firewall rule table contains
a list of policies that associated to the rule, and each firewall policy table
contains a list of firewall IDs associated to the policy.

References
==========
[1] https://wiki.openstack.org/wiki/Neutron/FWaaS/NewtonPlan

[2] https://specs.openstack.org/openstack/neutron-specs/specs/mitaka/fwaas-api-2.0.html

