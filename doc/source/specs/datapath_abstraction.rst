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

All Dragonflow apps have a specific flow structure, and a specific location in
across OVS tables. When picking a table extra care must be taken to avoid
stepping on flows from another app. Additionally, in tables where a branching
decision has to be made, priorities have to be coordinated as well. Finally,
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


This representation suggests a graph with states and transitions, i.e. a state
machine, with each block as above being a piece of logic contained within the
boundaries of the application. This will be called *DatapathElement*, it will
contain the following attributes:

* Entrypoints (1+) - start states within the element.
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

Once we have all apps, we can to construct the datapath itself, i.e. how apps
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
  | VM ingress +---> PortSec +---> SecGroups +---> L2 +---> L3 port filter +-->
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

.. code::

  digraph dragonflow {
    provider:out_all -> l2:in_all
    vm-ingress:out_all -> portsec:in_all
    portsec:out_accept -> secgroup:in_all
    secgroup:out_accept -> l2:in_all
    l2:out_unicast -> l3-filter:in_all
    l3-filter:out_match -> egress-fw:in_all
    egress-fw:out_accept -> l3:in_all
    l3:out_all -> ingress-fw:in_all
    ingress-fw:out_accept -> l2:in_all
  }


Translation
~~~~~~~~~~~
In the first stage, we're aiming at supporting OVS applications, and will model
model above states and transitions based on OVS tables and flows. Variables
will be allocated on top of register and metadata fileds.

Each application will declare the following (actual syntax subject to change):

.. code:: python

  class MyApplication(BaseDfApplication):
      def __init__(self, ldp, *args, **kwargs):
          # Descriptive name
          self.name = 'MyApplication'

          # Tables we need to allocate
          self.my_states = {
              'input': ldp.create_table(),
              'internal': ldp.create_table(),
          }

          # Entrypoints exported to the configuration level
          self.entrypoints = {
              'input1': ldp.create_entrypoint(
                  target_state=self.my_states['input'],
                  requires=('source_port_key', 'network_key'),
              ),
          )

          # Exitpoints - managed tables where config code will patch things
          # together
          self.exitpoints = {
              'output1': ldp.create_exitpoint(
                  provides=('custom_key1',),
              ),
              'output2': ldp.create_exitpoint(
                  provides=('custom_key2',),
              ),
          )

     def install_some_flows(self):
         self.my_transition = self.my_states['input1'].add_transition(
             condition=dp.conditions.And(
                 dp.conditions.DstMac(value='11:22:33:44:55:66'),
                 dp.conditions.EtherType(value=ether_types.IP),
             ),
             actions=(
                 dp.CopyField(
                     source=Field(
             next_state=self.my_states['internal'],
        )

     def remove_some_flows(self):
         self.my_transition.remove()

In this example, an application defines its states and entry/exit points with
the relevant variables. Datapath backend will allocate tables and registers to
those objects.

State transition manipulation will be translated to relevan flow modification
on the source table.

Entry and exit point of applications will be connected by a single flow each
on by the local controller (based on the configuration)

References
==========

