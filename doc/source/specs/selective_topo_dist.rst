..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode


===============================
Selective Topology Distribution
===============================

https://blueprints.launchpad.net/dragonflow/+spec/selective-topo-dist

This spec describes the design of a topology distribution mechanism. It pushes
topology only to Dragonflow local controllers that need it.

Problem Description
===================
Currently, Dragonflow local controllers cache all the topology, such as all the
networks, ports and routers etc. In fact, one compute node only has dozens of VMs.
Topology used by these VMs is merely a tiny proportion of the whole data center
networking topology. Most of the topology cached by Dragonflow local controllers
will never be used.

Moreover, in order to keep all the cached topology up to date, local controllers
have to repeatedly communicate with the Dragonflow database to refresh the data.
With the increase of compute nodes, communication of this type will also increase
correspondingly. For Dragonflow local controllers, this method will cause high
CPU and memory occupation rate. For the Dragonflow database, it's more intolerable,
for there will be too many update requests from tens of thousands compute nodes
to process.

Proposed Change
===============

basic idea
----------

The idea is quite simple:

  * Each Dragonflow local controller only subscribes topology it's interested in
    from the sub-pub server.

  * When northbound topology changed, in addition to save it to the Dragonflow
    database, Neutron plugin also publish the change to the sub-pub server.

  * When southbound topology changed, in addition to save it to the Dragonflow
    database, Dragonflow local controllers also publish the change to the sub-pub
    server.

  * On receiving a publish request from Neutron plugin or Dragonflow local controller,
    the sub-pub server publishes the change to whom subscribe the change.

  * When receives a published event, Dragonflow local controller updates its local
    cache and flow entries if needed.

  * When receives a published event, Neutron plugin updates it's status if needed.

Publisher subscriber pattern
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Selective topology distribution depends on the sub-pub function which is shown in
the following diagram. When there is a topology change, for example, a new port
is created by a tenant, a publisher (in this case, the Dragonflow Neutron plugin) will
publish this event together with detailed info of the new port to a topic. Every
topic maintains a list of subscribers. On receiving an event from publisher, the topic
then sends the event to every subscriber in the list. For the port creating example,
there may be many Dragonflow local controllers which have ports connecting to the
same network with the new port. These local controllers care about changes of ports
in the network and will subscribe change of this network by registering to the
corresponding topic. These controllers will get notified by the topic when this
new port is created.

::

                                       +--------------+
                                   +---> Subscriber A |
                                   |   +--------------+
                                   |
                      +---------+  |
                 +----> Topic A +--+   +--------------+
 +-----------+   |    +---------+  +--->              |
 | Publisher +---+                     | Subscriber B |
 +-----------+   |    +---------+  +--->              |
                 +----> Topic B +--+   +--------------+
                      +---------+  |
                                   |
                                   |   +--------------+
                                   +---> Subscriber C |
                                       +--------------+

Two ways to distribute topology selectively
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
There are many types of topology change. In large scale data center, number of
tenants is also considerable. There will be tons of topics if publish different
events to different topics. To simplify the implementation, some degree of convergence
has to be taken into account. There are two ways to converge the types of topology
change.

One topic per tenant
""""""""""""""""""""
Every tenant has one and only one topic. All kinds of topology changes of the
tenant are sent to this topic.

**Pros**

Easier for Publishers to decide which topic to publish.

Easier for Subscribers to decide which topic to subscribe.

**Cons**

Subscriber may receive redundant event and store additional topology it will never
use.

One topic per vpc or router
"""""""""""""""""""""""""""""""
Every vpc or router has its own topic. For isolated networks which don't connect
to any routers, they also have their own topics. Changes in topology are published
to the corresponding topics.

**Pros**

Finer grained. When a tenant has many vpc or routers or isolated networks, topology
changes of different vpc, routers or networks will not affect each other.

**Cons**

Harder for subscribers and publishers to decide which topic they should subscribe
or publish.

Here, I will only discuss the first way for simplicity.

Detailed design
---------------

Northbound Topology Change
^^^^^^^^^^^^^^^^^^^^^^^^^^

When a tenant named tenant1 create a port through Neutron's northbound api.

* Dragonflow Neutron plugin will publish a event to the tenant's topic in the
  sub-pub server.

* The sub-pub server will then check who have subscribed the topic and publish
  the event to them.

* On receiving the event, local controllers will save the new port's information
  and install some flow entries on OVS which is not covered in this spec.

::

 +----------------+ +----------------+ +------------------+  +------------------+
 | Neutron plugin | | Sub-pub Server | | Dragonflow local |  | Dragonflow Local |
 +-------+--------+ +------+---------+ | Controller 1     |  | Controller2      |
         |                 |           +--------+---------+  +--------+---------+
         |                 |                    |                     |
         |                 |                    |                     |
         | publish(tenant1)|                    |                     |
         +----------------->                    |                     |
         |                 |   publish(tenant1) |                     |
         |                 +-------------------->                     |
         |                 |                    |                     |
         |                 |                    |                     |
         +                 +                    +                     +

In the above diagram, Dragonflow local controller 2 has no VMs belong to tenant1.
It will not subscribe tenant1's topic and therefore will not get notified.

Processing of other northbound topology changes, such as creating, deleting or
modifying router, network and port is same as the above example.

Southbound Topology Change
^^^^^^^^^^^^^^^^^^^^^^^^^^

When nova starts a VM in a compute node, it will insert a port on the corresponding
OVS bridge.

* By monitoring OVSDB, Dragonflow local controller get notified when the new port
  is added on OVS bridge.

* Dragonflow local controller queries the port's topology from Dragonflow database
  and knows which tenant the port belongs to.

* Dragonflow local controller queries local cache to see if it has subscribed the
  tenant topic.

  + If local controller has already subscribed the tenant's topic. This means there
    already are local ports of the same tenant. It will not subscribe the topic again.

  + If local controller hasn't subscribed the tenant's topic. This means the new
    port is the only local port in the compute node belongs to the tenant. Local
    controller will subscribe the tenant's topic.

::

 +----------+   +----------------+ +------------------+
 | database |   | sub/pub server | | Dragonflow local |
 +-----+----+   +------+---------+ | Controller 1     |
       |               |           +--------+---------+
       |               |                    |
       |               |                    |
       |               |                    +----+ new OVS port
       |               |                    |    | online
       |               |                    <----+
       |  Get port's topology form database |
       <------------------------------------+
       |               |                    |
       |               |                    |
       |               | subscribe(tenant1) |
       |               <--------------------+
       |               |                    |
       |               |                    |
       +               +                    +


If nova remove a port from OVS bridge, local controller will check if it's the
tenant's last port on the compute node. If it is, local controller will unsubscribe
the tenant's topic and will not receive any further event of the tenant's topology
changes.

Dragonflow Local Controller Startup
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
On startup, local controller will get all ports being attached to OVS bridge by
querying OVSDB. Once getting all these local ports, local controller will query
ports' topology from Dragonflow database and subscribe the corresponding topics of
the ports. This is done for every local port, as described in the previous section.

Dragonflow Local Controller Offline
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
If one local controller exit, for example, killed by administrator for maintenance,
connection to the sub-pub server will lose. It's the sub-pub server's responsibility
to remove the local controller from all topics it has subscribed.
