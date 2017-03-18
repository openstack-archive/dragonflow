..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

========================
Neutron Interoperability
========================

 https://blueprints.launchpad.net/dragonflow/+spec/neutron-interoperability

Neutron interoperability support enables Compute nodes with dragon flow local controller
share overlay connectivity with compute nodes using neutron reference implementation.

Problem Description
===================
Currently Dragonflow compute hosts share overlay connection only among them-self.
This complicates the migration to Dragonflow.
Mandates a strict deployment topology.

Mech-driver
-----------
Dragonflow mech-driver is run as a neutron ml2 plugin. It is responsible for interception
of network CRUD events ( network, port, sg) and propagate to the Dragonflow nodes using
Dragonflow's distribution mechanism. When a logical port is added outside of dragon-flow 
compute nodes, it is being neglected by the df-local-controller.
  

Proposed Change
===============

Configuration
-------------
To support interoperability with other neutron based networking drivers. A global 
configuration flag is added to indicate if dragon flow compute node topology is
mutually exclusive.

A configurable list of supported agents to indicated overlay connectivity with the 
remote compute node running this interoperable agent.

Code
----
In order to support other agents running on alien compute hosts. The mech driver will
process notification of agent create, update and delete events, filter out supported agents
in the compatibility list, and distribute the existence of the compute node among the df-compute
nodes.

From that point-on the nodes running Dragonflow, should treat alien's port notifications the same
as if that port notification is made on df -node.
