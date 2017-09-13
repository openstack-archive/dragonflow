..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
Logical datapath modeling
=========================

Include the URL of your launchpad RFE:

https://bugs.launchpad.net/dragonflow/+bug/example-id

Dragonflow heavily relies on OpenFlow and Open vSwitch to implement its
datapath. While those are natural fit for our purposes, OpenFlow's reliance on
IDs (tables, groups, etc) creates a massive coupling between our apps.

This spec aims to propose a generic abstraction of datapath, that would allow
coupling at much higher level (e.g. apps vs tables), and introduce a more
backend neutral language.

Problem Description
===================

All of our apps have a specific flow structure, and a specific location in
across our tables. When picking a table extra care must be taken to avoid
stepping on flows from another app. Additionally, in tables where a branching
descision has to be made, a priorities have to be coordinated as well. Finally,
when some app decides to store some kind of state on the packet, it has to make
sure the register used does not contain any special info another app will
expect to find later on.

Proposed Change
===============

As stated in the introduction, we'd like to introduce a logical datapath, that
will be based on higher level concepts. This datapath will then be "compiled"
to the target representation.

Let us start with definitions bottom-up:

Currently, each app does a one or several filters and transformations. For
example, we can look at L2 app. It has a single step in our datapath: Take
packet's network and destination MAC, and look up a port that matches this MAC.
Store the destination key in the state, e.g.

.. code::

  l2_lookup(packet):
    if is_unicast(packet.eth.dst):
      key = packet.state.network, packet.eth.dst
      packet.state.dst_port = lookup[key]
      next()
    else:
      foreach port in get_ports(packet.state.network):
        packet.state.dst_port = port
        next()

We can represent it as:

::

   L2 lookup
  +-----------------------------------------------------------+
  |                                                           |
  |  +-------+             +---------+  lookup    +--------+  |
  |  |       | dst is uni  |         |  dest port |        |  |
  |  | start +-----+-------> unicast +------------> done 1 |  |
  |  |       |     |       |         |            |        |  |
  |  +-------+     |       +---------+            +--------+  |
  |                |                                          |
  |                |                    replicate             |
  |                |       +---------+  for each  +--------+  |
  |                |       |         |  port      |        |  |
  |                +-------> brdcast +------------> done 2 |  |
  |               else     |         |            |        |  |
  |                        +---------+            +--------+  |
  |                                                           |
  +-----------------------------------------------------------+


This representation suggests a graph with states and transitions, with each
block as above being a piece of logic contained within the boundaries of the
application. This will be called *DatapathElement*, it will contain the
following attributes:

* Entrypoints (1+) - start states within the element
* Exits (1+) - final states within the element
* Arbitrary states - vertices in the above graph
* Transitions - the edges described above. Each edge will have a condition
  attached to it, that will dictate when the transition will happen and an
  action, that will mutate packet's state (either fields or metadata)

To store extra information about the packet, an app will be able to define
'variables' - a logical definitions that will reserve the relevant packet
specific storage space. A variable will be either local - internal to the
element (to app information between internal states) or global, if the
information will be required for other apps or other elements of the same app.

Each app will define the variables it provides publically, and variables it
consumes. This will be used for datapath assembly, and checking correctness.

Once we have our apps, we have to construct the datapath itself, i.e. how apps
interact one with the other.

We would like to chain the final state on one app to the start state of another
and so on. In the inter-app graph, there are no conditional edges. All
descisions happend at app's datapath element level.

Example:

::

   +----------+
   |          |
   | Provider +-------------------------------------+
   |          |                                     |
   +----------+                                     |
                                                    |
  +------------+   +---------+   +-----------+   +--v-+   +----------------+
  |            |   |         |   |           |   |    |   |                |
  | VM ingress +---> PortSec +--->  SecGroup +---> L2 +---> L3 port filter +-->
  |            |   |         |   |           |   |    |   |                |
  +------------+   +---------+   +-----------+   +--^-+   +--+-------------+
                                                    |        |
                                                    |        |
                                                    |     +--v--------+
                                                    |     |           |
                                                    |     | Egress FW |
                                                    |     |           |
                                                    |     +--+--------+
                                                    |        |
                                                    |        |
                                          +---------+--+  +--v--+
                                          |            |  |     |
                                          | Ingress FW <--+ L3  |
                                          |            |  |     |
                                          +------------+  +-----+

The above can be defined with a configuration level language (e.g. DOT):

.. code:: dot

  digraph dragonflow {
    provider -> l2
    vm-ingress -> portsec -> secgroup -> l2 -> l3-filter -> ...
    l3-filter.match -> egress-fw -> l3 -> ingress-fw -> l2
  }


Translation
~~~~~~~~~~~

TDB

References
==========

