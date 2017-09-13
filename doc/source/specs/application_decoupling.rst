..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

======================
Application decoupling
======================

Dragonflow heavily relies on OpenFlow and Open vSwitch to implement its
datapath. While those are natural fit for our purposes, OpenFlow's reliance on
IDs (tables, groups, etc) creates a massive coupling between Dragonflow apps.

This spec aims to propose a generic abstraction of datapath, that would allow
coupling at much higher level (e.g. apps vs tables), and introduce a more
backend neutral language.

Problem Description
===================

All Dragonflow apps have a specific flow structure, and a specific location
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
interaction with other apps will be managed through the local controller.

At the highest level, local controller will create and maintain a datapath.
The datapath itself will be composed of various (datapath) elements, managed
by different apps:

::

  +--Datapath--------------------------------+
  |                                          |
  |     +---------+            +---------+   |
  |     |         |            |         |   |
  |     | App     +------------> App     |   |
  |     |         |            |         |   |
  |     +---+-----+            +---------+   |
  |         |                       ^        |
  |         |     +---------+       |        |
  |         |     |         |       |        |
  |         +-----> App     +-------+        |
  |               |         |                |
  |               +---------+                |
  |                                          |
  +------------------------------------------+

Each app will be considered a single datapath element. Each element will define
its states/tables, entry/exitpoints and used variables:

::

  +---------+---App-------+---------+
  |         |             |         |
  > Entry1  | Used tables | Exit1   >
  > Entry2  | and regs    | Exit2   >
  > Entry3  |             | ...     >
  | ...     |             |         |
  +---------+-------------+---------+

.. code:: python

  class SomeApp(AppBase):
      schematic = Contract(
          # List of application states
          states=('STATE1', 'STATE2'),

          # Outwards facing variables
          public_mapping=VariableMapping(
              source_port_key='reg6',
              network_key='metadata',
              result1='reg1',
          ),

          # Internal variables
          private_mapping=VariableMapping(
              temp_state='reg7',
          ),

          entrypoints=(
              Entrypoint(
                  name='entry1',
                  target='STATE1',
                  consumes=('source_port_key', 'network_key'),
              ),
              Entrypoint(
                  name='entry2',
                  target='STATE1',
                  consumes=('source_port_key', 'network_key'),
              ),
              Entrypoint(
                  name='entry2',
                  target='STATE2',
                  consumes=('source_port_key', 'network_key'),
              ),
          ),

          exitpoints=(
              Exitpoint(
                  name='exit1',
                  produces=('result1',)
              ),
              Exitpoint(
                  name='exit2',
              ),
          )
      )


Local controller will receive an external configuration for datapath layout,
and will create the relevant links between the elements. All links will be
described in a simple format, we can use DOT or come up with our own.

The application list as it is will be removed, and applications will be
instantiated based on what is defined in the wiring configuration.

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
  | VM egress  +---> PortSec +---> SecGroups +---> L2 +---> L3 port filter +-->
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
    # apps:
    in[type="input", params="...",];
    pr[type="provider"];
    l2[type="l2"];
    ps[type="portsec"];
    sg[type="sg"];
    l3[type"l3-proactive"];
    fw[type="fw"];


    # connections:
    pr:out:default           -> l2:in:default;
    in:out:vm-egress         -> ps:in:default;
    ps:out:accept            -> sg:in:egress;
    sg:out:egress-accept     -> l2:in:default;
    l2:out:unicast           -> l3:in:ingress-filter;
    l3:out:ingress-match     -> fw:in:egress;
    fw:out:egress-accept     -> l3:in:route;
    l3:out:post-route        -> fw:in:ingress;
    fw:out:ingress-accept    -> l2:in:default;
  }

In the above config, edges are connected between entrypoints and exitpoints.
The notation specified by: APP_INSTANCE:ENDPOINT_TYPE:ENDPOINT_NAME

It should be noted that applications can be instantiated several times this
way.

.. code::

  trunk_vlan[type="trunk", seg_types="vlan"];
  trunk_macvlan[type="trunk", seg_types="macvlan"];
  trunk_ipvlan[type="trunk", seg_types="ipvlan"];


Those instances will be then wired independently.

On the application level, we'll leave most of the code unchanged. Each
application will declare the groups, tables, and registers it needs. After
app initalization, datapath code will allocate all required IDs. The
application will use the allocated IDs rather that constants currently used.

We will impose further restrictions on application code, the application ...

 * ... will not install flows outside in its private tables.
 * ... will goto/resubmit only into its own tables.
 * ... will read/write only to registers it declares as used.
 * ... will only use groups it allocated.
 * ... will packet in only on its own tables.
 * ... will inject packet out only to its own tables.

Ingress (table=0) / egress (output:PORT) actions will be performed by
dedidicated input/output elements.

Back on the controller level, the wiring of the elemnts will stay static
throughout controller's execution, with a single flow per graph edge.
Each transition will take care to move relevant values into the right registers
and move unrelated values out of the way if app will use their registers
internally.

The following edge:

::

  +-------------+    +-----------+
  |APP1         |    |APP2       |
  |             |    |           |
  |      EXIT1 +------>ENTRY1    |
  |             |    |           |
  |   vars:     |    |  vars:    |
  |   a: reg1   |    |  a: reg6  |
  |   b: reg2   |    |  b: reg7  |
  |             |    |           |
  +-------------+    +-----------+


Will be translated into:

.. code::

  table_id=APP1:out:EXIT1, match=*any*,actions=move(reg1->reg6),move(reg2->reg7),goto:APP2:in:ENTRY1.target

References
==========

