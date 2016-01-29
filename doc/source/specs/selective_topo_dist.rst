
..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode


===============================
Selective Topology Distribution
===============================

This spec describe the design of a topology distributing mechanism. It push
topology info only to Dragonflow local controllers that need the info.

Problem Description
===================
Currently, Dragonflow local controller caches all the topology info, for example
all the networks, ports and routers etc. In fact,one compute node only have dozens
of virtual machines and topology info used by these VMs is merely a tiny part of
the topology of the whole data center networks. Most of the info cached by Dragonflow
local controller will never be used by the controller.

Moreover, in order to keep all the cached topology info up to date, local controllers
have to repeatedly communicate with the Dragonflow database. With the increase of
compute nodes, communication of this type will also increase correspondingly. For
Dragonflow local controllers, this method will cause high CPU and memory occupation
rate. It's more disastrous to Dragonflow database, for there will be too many request
from tens of thousands compute nodes for it to process.

Proposed Change
===============

basic idea
----------

The idea is quite simple: each Dragonflow local controller subscribe topology info
it's interested in from the sub-pub server. When topology changed, in addition to
save it to the Dragonflow database, neutron plugin or Dragonflow local controller
has to publish the change to the sub-pub server also. The sub-pub server then
publishes the change to who that subscribe the change.

Publisher subscriber pattern
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Selective topology distribution depends on the sub-pub function which is shown in
the following diagram. When there is a topology change, for example, new port
created by a tenant, a publisher(in this case, the Dragonflow neutron plugin) will
publish this event together with detailed info of the new port to a Topic. Every
topic records a list of subscribers. On received a event from publisher, the topic
will send the event to every subscribers in the list. For the port creating example,
there may be many Dragonflow local controllers which have ports connecting to the
same network with the new port. These local controllers care about changes of ports
in the network and will subscribe change of this network by registering to the
corresponding topic. These controllers will get notified by the topic when this
new port is added.

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

Tow ways to distribute topology selectively
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
There are many type of topology change. In large scale data center, number of
tenants is also considerable. There will be tons of topics if publish different
events to different topics. The implementation will be too complex. Some degree
of convergence have to be taken into accounted to simplify the situation. There
are two way to converge the types of topology change.

One topic per tenant
""""""""""""""""""""
One tenant has only one topic. All kinds of change in topology of the tenant are
sent to this topic.

**Pros**

Easier for Publisher to decide which topic to public.

Easier for Subscriber to decide which topic to subscribe.

**Cons**

Subscriber will receive redundant event and store additional topology it will never
use.

One topic per vpc or router
"""""""""""""""""""""""""""""""
Every vpc or router has it own topic. For isolated network which doesn't connect
to any router, it also it own topic. Change in topology are published to the
corresponding topic.

**Pros**

Finer grained. When a tenant have many vpr or routers or isolated networks, Change
in topology of different vpc or routers or networks will not affect each other.

**Cons**

Harder for subscriber and publisher to decide which topic they should subscribe
or publish.

Here, I will only discuss the first way for simplicity.

Detailed design
---------------

Northbound Topology Change
""""""""""""""""""""""""""

When a tenant named tenant1 create a port through neutron's northbound api,
neutron's Dragonflow plugin will publish a event to tenant's topic in the sub/pub
server. The sub/pub server will then check who have subscribed the topic and
publish the event to them. On receiving the event, local controller will save
the new port's information and install some flow entries on OVS which is not
covered in this spec.

+----------------+ +----------------+ +------------------+  +------------------+
| neutron plugin | | sub/pub server | | Dragonflow local |  | Dragonflow Local |
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

Processing of other northbound topology change, such as creating, deleting or
modifying router, network and port are same as the above example.

Southbound Topology Change
""""""""""""""""""""""""""

When nova startup a VM on a host, it will insert a port on the corresponding OVS
bridge. On knowing a new OVS port online, Dragonflow local controller queries
port's topology from database and knows which tenant the port belongs to. After
that, local controller will subscribe the tenant's topic.

+----------------+ +------------------+
| sub/pub server | | Dragonflow local |
+------+---------+ | Controller 1     |
       |           +--------+---------+
       |                    |
       |                    |
       |                    +----+ new OVS port
       |                    |    | online
       |                    <----+
       |                    |
       |                 Get port's topology
       |                 from database
       |                    |
       | subscribe(tenant1) |
       <--------------------+
       |                    |
       |                    |
       +                    +

If nova remove a port from OVS bridge, local controller will check if it's the
tenant's last port on the host. If it is, local controller will unsubscribe the
tenant's topic and will not receive any further event of the tenant's topology
change.
