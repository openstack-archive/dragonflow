..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
Support VM live migration
=========================

https://blueprints.launchpad.net/dragonflow/+spec/vm-live-migration

VM live migration is an important feature in Openstack, native Neutron has
supported it, so any SDN controller based design in Neutron should support
it, including Dragonflow.

Problem Description
===================

Currently, Dragonflow does not support VM live migration. When VM is
migrated from one compute node to another, the flows won't be updated
correctly, including L2, L3, DNAT, etc. So, what this spec will do is to
ensure the flows are updated correctly and fastly, to make sure the
downtime of network as short as possible.

For more information about VM live migration, refer to [#]_.

.. [#] http://docs.openstack.org/admin-guide/compute-live-migration-usage.html

Proposed Change
===============

To support VM live migration, we must understand the interaction between
nova and neutron during migration, and in general there are three points
we should pay attention to.

1 VIF plugged in destination node.

2 VIF unplugged in souce node.

3 Nova calls Neuron API(update_port) to update port host ID information.

In order to make sure the downtime of network as short as possible, we
should update flows when the VM is really down at source node. As the above
analysis, VM is shut down at the second step, and we should update flows
simultaneously in all related nodes, including source node, destination
node, and other related nodes. The interval between the second and third
steps is uncertain, but we can also update flows in the third step to make
sure the flows are updated correctly if it doesn't update flows in the
second step correctly because of some problems.

NB Data Model Impact
--------------------

There is a new field called port-migration to indicate if the port is in
migration. It's not necessary to save the field to DB store in compute node,
just in df-db, as the field should be accessed by controllers in source
and destination node to synchronize state.

Publisher Subscriber Impact
---------------------------

The publisher function should be enabled in compute node, to send flow
update event in the second step.

Dragonflow Applications Impact
------------------------------

None

Installed flows Impact
----------------------

None

Implementation
==============

As described above, the VM live migration could be mainly divided into
three steps:

1 When a new port is online in destination node, controller check whether
the chassis is equal to self chassis. It will be the VM live migration
scenario if the port's chassis not equal to the self chassis, and then
setting the port migration to self chassis.

2 When the port is offline in source node, controller will query the NB
database to check if the port has the port state field, and if yes, it
will be treated as VM live migration, then publish migration event to
all related nodes to notify flows update, including destination node,
source node, and other nodes which have subscribed the same topic as the
migrating VM.

3 At the last stage, neutron calls update_port to update port chassis.
And controller will respond to the publish event from the neuron server.
The controller can either update migration flows or not in this step,
so if it does, it will ensure the flows are updated correctly in condition
the second step fail to update flows, such as publish event missing.

We try to use the existing interfaces when update flows, to avoid making
too many changes to the existing architecture. At present, almost all
Dragonflow apps have implemented both adding and removing local/remote
port, so we should use these interfaces, not adding new ones.
