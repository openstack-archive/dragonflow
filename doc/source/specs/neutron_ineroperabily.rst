..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

========================
Neutron Interoperability
========================

 https://blueprints.launchpad.net/dragonflow/+spec/neutron-interop

Neutron interoperability support enables Compute nodes running Dragonflow
local controller share overlay connectivity with compute nodes running neutron
agent.

Problem Description
===================
Currently Dragonflow compute hosts share overlay connection only among
them-selves. Even tough Dragonflow makes use of the same virtual network
identifiers, it does not support overlay connectivity with non Dragonflow 
compute nodes
This result's in:

* Complicated migration to Dragonflow.
* Mandating a strict deployment topology.

Mech-driver
-----------
Dragonflow mech-driver is run as a neutron ml2 plugin. It is responsible for
interception of network CRUD events ( network, port, sg) and propagate to the
Dragonflow nodes using Dragonflow's distribution mechanism. When a logical port
is added outside of Dragonflow compute nodes, it is being neglected by the
df-local-controller.


Proposed Change
===============

Configuration
-------------
A boolean interoperability 'networking_interop' flag is added, to support
interoperability in general.

A configurable list 'interop_networking_types' of supported agents used to
indicate overlay connectivity with remote compute nodes running this
one of interoperable agent.


Code
----
In order to support other ml2 based agents running on non Dragonflow compute
hosts at the same time. Where each compute node run a single L2 mechanism,
Dragonflow or other. The mech driver will process notification of agent create,
update and delete events, filter in the supported agents according to the
compatibility list, and distribute the existence of the non Dragonflow compute
node among the Dragonflow compute nodes.

From that point-on the nodes running Dragonflow, should treat non Dragondlow 
compute port notifications the same as if that port notification is made on
Dragonflow compute node.


