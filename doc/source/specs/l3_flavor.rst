..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

================================
Stand-alone Dragonflow L3 flavor
================================

https://bugs.launchpad.net/dragonflow/+bug/1698651

Problem Description
===================

Dragonflow allows fully distributed L3 routing and source NATing. Those
features attracted some attention in the community. In this spec we'll describe
how Dragonflow's L3 capabilies can be used along-side Neutron's reference
implementation.


Proposed Change
===============

In Netwon release, Neutron introduced extensible L3 plugin. Before this change,
an operator could deploy the reference L3 plugin and use the reference
implementations for all routers, or use another plugin. There was no way
to implement part of the routers with one implementation, and the others with
another. The new L3 plugin featured router flavors. Each router can be
implemented by a specific flavor (driver), and 3rd parties can implement their
functionality within the bounds of a flavor, instead of a whole L3 plugin. This
allows deployment of routers with different implementations side-by-side.

In Dragonflow's current architecture, we're implementing a whole L3 plugin.
Thus all routers run Dragonflow implementation. Since our L3 is implemented
inside the integration bridge, it is healivy dependent on the Dragonflow L2
implementation.

In order to support the standalone Dragonflow L3 use-case, we'll need to createa Dragonflow L3 flavor and an L3 agent to implement it. The initial idea is
to implement the interface to reference L2 implementation. The motivation
behind supporting reference inteface is that it is standart enough to require
3rd parties to use it when interfacing Dragonflow L3.

The system components we'll need are:

* L3 flavor - for managing L3 models
* ML2 mech driver - for getting info on other relevant models (e.g networks,
  subnet, ports).
* Northbound database/pubsub - to store Dragonflow models and send
  notifications. (since etcd is a common service now, we can avoid deploying
  anything else).
* L3 agents - a modified version of Dragonflow's local controller:

 * Will be managing (preferably) an independent bridge (br-l3), connected by
   patches to the integration bridge.
 * This agent will feature a reduced set of apps, relevant to the L3
   functionality it has to provide: L3 routing/SNAT/Floating IPs
 * We will also need custom classification/dispatch, to handle packets coming
   from and to integration brdige.

::

 +--------------+   +--------------------+
 | DF L3 flavor |   | DF ML2 mech driver |
 +------+-------+   +-------+------------+
        |                   |
        v                   |
  NB-DB/Pub-Sub  <----------+
        +
        |
        |
        |
  +-----v-------+              +-------------------+
  | DF L3 agent |              | openvswitch agent |
  +----------+--+              +------------+------+
             |                              |
    controls |                     controls |
             |                              |
             |                              |
             |                              |
    +--------v---------+       +------------v-----+
    | br-l3            |       | br-int           |
    |  * Routing       +------->                  |
    |  * SNAT          |       |                  |
    |  * DNAT          <-------+                  |
    |                  |       |                  |
    +------------------+       +------------------+


In this implementation, our apps can stay relatively the same, as long as we
provide them with an environment similar to Dragonflow's br-int (metadata/regs)
We will need to adapt the customized classification/dispatch flows to fill in
the relevant information.

In the reference implementation each router interface or gateway is a separate
port because each one goes to a different network namespace. Since all our
routers are now implemented in a single bridge, we don't need so many ports.
We can use packet_mark to pass the relevant data (e.g. what router interface
we're accessing).

For chassis SNAT we'll need to add a patch port towards the external network
bridge.


::

 Reference implementation:

 +--------------+
 |  br-int      |
 |              |
 +--+--+--+--+--+
    |  |  |  |         +-------------------+
    |  |  |  |         | router1 namespace |
    |  |  |  +---------+                   |
    |  |  +------------+                   +--+
    |  |               |                   |  |     +-----------+
    |  |               +-------------------+  |     |   br-ex   |
    |  |                                      +-----+           |
    |  |               +-------------------+  +-----+           |
    |  |               | router2 namespace |  |     +-----------+
    |  +---------------+                   +--+
    +------------------+                   |
                       |                   |   Router gateways
  Router interfaces    +-------------------+


  Dragonflow standalone L3:

  +------------+        +-----------+        +-----------+
  |   br-int   |        |   br-l3   |        |   br-ex   |
  |            +--------+           +--------+           |
  +------------+        +-----------+        +-----------+

References
==========

* L3 flavors

  https://specs.openstack.org/openstack/neutron-specs/specs/newton/multi-l3-backends.html

