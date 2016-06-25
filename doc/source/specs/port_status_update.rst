This work is licensed under a Creative Commons Attribution 3.0 Unported
License.

http://creativecommons.org/licenses/by/3.0/legalcode

===================
Port status update
===================

https://blueprints.launchpad.net/dragonflow/+spec/port-status-update

This blueprint describes how to support port status update for
Dragonflow.

Problem Description
=====================
Port status update feature will enable synchronization of port status
between DF DB and neutron DB.

There is only port status in DF database updated after ports are created
currently leaving Neutron DB port status unchanged. Because of the status
of port in neutron remains the same before and after DF DB processed, thus no
event being sent to nova.

Proposed Change
===============

Design principle
----------------

DF ML2 mechanism driver subscribe special a topic which selected randomly
and sent by publisher from each compute node.

When nova create a VM, it will call neutron API create_port. Local
controller on compute node is notified to process the port, then it
changes DF DB, and publishes event at last.

DF ML2 mechanism driver will update relative data in neutron DB afer
receive message from publisher with the specific topic.

Publisher subscriber pattern
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Port status update feature depends on the sub-pub function shown in the
following diagram. When there is a port status change, for example, nova
create a VM which scheduled to compute A. Publisher A will send event
with the topic(port_status_update specific).Once receiving the notification
from publisher, the subscriber in server node will invoke callback function,
and finally changes port status in neutron DB.

We need to consider that there should be only one neutron server to process
the event simultaneously and that all neutron servers will have equal chance
to handle the event.

A kind of LB will be introduced. There are several servers(A,B,C,D...),to
which each neutron server will publish, for example, neutron server A
will subscribe to topic A, neutron server B will subscribe to topic B, etc.
Each local controller will publish different topic according to the result
of random method in the range of number of servers.

It is assumed that there are 4 server nodes and several compute nodes. Base
on the previous description, there are 4 topics, which will be subscribed
by each server node, stored in DF DB. Sever node will update its topic
timestamp stored in DF DB which representing it status. If a new server
node is added to server cluster, it will add a new topic to DF DB, and
next time the compute node might use it to publish event.

On the other side, all compute nodes will have a random algorithm(the result
can not exceed the total number) which will select random topic stored in DF
DB to send event of port status update..

::

    +------------+     +---------+         +----+        +--------------+
    | SubscriberA <---   Topic A    <----  |    |   <----+ Publisher X  |
    +------------+     +---------+         | R  |        +--------------+

    +------------+     +---------+         | A  |        +--------------+
    | SubscriberB <---   Topic B    <----  | D  |   <----+ Publisher Y  |
    +------------+     +---------+         | O  |        +--------------+

    +------------+     +---------+         | M  |        +--------------+
    | SubscriberC <---   Topic C    <----  |    |   <----+ Publisher Z  |
    +------------+     +---------+         +----+        +--------------+


The topic for port status
"""""""""""""""""""""""""
The special topic defined for port update status event is shared by all
tenants.

Pros and Cons
-------------
Pros

There are several neutron servers which will join in processing subscriber
events concurrently, so it can alleviate the pressure of each server
effectively.

Cons

There is only one thread to process events being published from several
compute nodes at the same time. Its won't be a serious problem when
there are a few nodes, but we should evaluate the process capability of
the server in detail while there are too many compute nodes, especially
when all compute nodes are online concurrently.

