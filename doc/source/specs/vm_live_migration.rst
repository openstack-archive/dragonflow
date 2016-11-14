..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

====================================
Support checking if chassis is alive
====================================

https://blueprints.launchpad.net/dragonflow/+spec/is-chassis-alive-support

VM live migration is important feature in openstack, native neutron has
supported it, so any SDN controller based design in neutron should support
it, including dragonflow.

Problem Description
===================

Curruntly, dragonflow do not support VM. When VM is migrated from one
compute node to another compute node, the flows won't be updated correctly,
including L2, L3, DNAT, etc. So, what this spec will do is to ensure the
flows are updated correctly and fastly, in order to make sure the downtime
of network is as short as possible.

Proposed Change
===============

To support VM live migration, we must understand the interaction between
nova and neutron while in migration, and there are three points we shoud
pay attention to.

1 VIF plugged in destination node.

2 VIF unplugged in souce node.

3 Nova calls neuron API(update_port) to update port chassis information.

In order to make sure the downtime of network is as short as possible, we
should update flows when the VM is really down at source node. As the above
analysis, the second step is VM downtime, and we should update flows
simultaneously in all nodes, including source node, destination node, and
other nodes. The interval between the second and third steps is uncertain,
but we can update flows in the third step also to make sure the flows are
update correctly if the second step don't update flows correctly because
of other problems.

NB Data Model Impact
--------------------

There is new field called port state to indicate if the port is in migraion.
This field is not necessary to save to DB store in compute node, just in
nouth DB, as the field should be accessed by controllers in source and
destination node to synchronize state.

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
setting the port state to self chassis.

2 When the port is offline in source node, controller will query the NB
database to check if the port has the port state field, and if yes, it
will be treated as VM live migration, then publish migration event to
all related nodes to notify flows update, including destination node,
source node, and other nodes which has subscribed the same topic as the
migrating VM.

3 At the last stage, neutron calls update_port to update port chassis.
And controller will respond to the publish event from the neuron server.
The controller can either update migration flows or not in this step,
so if does, it will ensure the flows are updated correctly in condition
the second step fail to update flows, such as publish event missing.

We try to use the existing interfaces when update flows, to avoid making
too many changes to the existing architecture. At present, almost all
dragonflow apps have implemented add_local_port, remove_local_port,
add_remote_port, remove_remote_port, so we should notify flows using
notify_add_local_port, notify_remove_local_port, notify_add_remote_port,
notify_remove_remote_port respectively and not use new interface like
update_local_port.



