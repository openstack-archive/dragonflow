 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==================
Classification App
==================

 https://blueprints.launchpad.net/dragonflow/+spec/classification-app

The classification is a separate processing which takes place throughout
the port's life-cycle.

When a packet enters the integration bridge, it is
classified. Information, such as its network ID and source's unique port
id are stored in the OVS metadata, i.e. in metadata field and registers.

This information is then used by other Dragonflow applications throughout
the pipeline.

Problem Description
===================

Currently, the L2 application contains setting up classification related
flows as well as setting up other port's life-cycle pipeline flows.

Separation of the classification related flows to a new dedicated
application, enables clear, straightforward, readable, and reusable code
that deals only with classification.

Reusability can be further pushed forwards by extracting common methods
to a common locations and libraries.

This change will allow appling classification at different points of packet
processing in the future, for example to support NSH use cases.

Proposed Change
===============

Dragonflow is composed of multiple applications working in tandem to
construct the pipeline.

The code that constructs the classification flows will be extracted to
its own Dragonflow application.

The classification application will install flows on table 0, where the
packet is received. It will set the following metadata information:

* metadata <- Unique network ID

* reg6 <- Unique ID of the packet source port (unique id)

The classification application adds the relevant flows upon the creation
of a new port, i.e. on the callback `add_local_port`.

An example flow, for a VM on ofport 3, with unique port ID 3, and network ID 1,
is:

::
    table=0, priority=100,in_port=3 actions=load:0x3->NXM_NX_REG6[],load:0x1->OXM_OF_METADATA[],resubmit(,1)

The classification application removes the relevant flows upon the
removal of a port, i.e. on the callback `remove_local_port`.

This change has the following benefits:

* The L2 application will be simplified, by removing code that is not
  L2-specific elsewhere.

* The new application will be reusable, regardless of which L2 application is
  used

* The new application will be simple, and will contain only
  classification-relevant code. This will improve readability and
  maintainability.

