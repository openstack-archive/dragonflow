..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
Logical datapath modeling
=========================

Dragonflow heavily relies on OpenFlow and Open vSwitch to implement its
datapath. While those are natural fit for our purposes, OpenFlow's reliance on
IDs (tables, groups, etc) creates a massive coupling between Dragonflow apps.

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

This spec proposes to isolate each app from all other applications. Each app
will define its contract (entrypoints, exitpoints, used registers). All
interation with other apps will be managed through the local controller.

At the highest level, local controller will create and maintain a datapath.
The datapath itself will be composed of various (datapath) elements, managed
by different apps:

::

  +--Datapath--------------------------------+
  |                                          |
  |     +---------+            +---------+   |
  |     |         |            |         |   |
  |     | Element +------------> Element |   |
  |     |         |            |         |   |
  |     +---+-----+            +---------+   |
  |         |                       ^        |
  |         |     +---------+       |        |
  |         |     |         |       |        |
  |         +-----> Element +-------+        |
  |               |         |                |
  |               +---------+                |
  |                                          |
  +------------------------------------------+

Each app will define a set of elements, marking points of its presence on the
datapath. Each such element will dictate its contract/interface.:

::

  +---------+---Element---+---------+
  |         |             |         |
  > Entry1  | Used tables | Exit1   >
  > Entry2  | and regs    | Exit2   >
  > Entry3  |             | ...     >
  | ...     |             |         |
  +---------+-------------+---------+

.. code:: python

  element = datapath.create_element(
      name='some-app',
      states=('STATE1', 'STATE2'),
      shared_variables={
          'network_key': 'metadata',
          'source_port_key': 'reg1',
      },
      private_variables={
          'temp-state': 'reg7',
      },
      entrypoints={
          'entry1': 'STATE1',
          'entry2': 'STATE1',
          'entry3': 'STATE2',
      },
      exitpoints=('exit1', 'exit2'),
  )


Local controller will receive an external configuration for datapath layout,
and will create the relevant links between the elements. All links will be
described in a simple format, we can use DOT or come up with our own.

Here's an example for a part of datapath, and its defined configuration:

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

On the application level, we'll leave most of the code unchanged. Each
application will define its elements. For each elements, it will declare the
groups, tables, and registers it needs. After element initalization, datapath
code will allocate all required IDs. The application will use the allocated IDs
rather that constants currently used.

Applications will receive further restrictions, the application ...

 * ... will install flows only in it's private tables
 * ... will goto/resubmit only into its own tables
 * ... will read/write only to registers it allocated.
 * ... will only use groups it allocated

Ingress (table=0) / egress (output:PORT) actions will be performed by
dedidicated input/output elements.

Back on the controller level, the wiring of the elemnts will stay static
throughout controller's execution, with a single flow per graph edge.
Each transition will take care to move relevant values into the right registers
and move unrelated values out of the way if app will use their registers
internally.

References
==========

