..
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

Currently, there is only port status in DF database being updated after
ports are created, leaving corresponding Neutron DB port status unchanged.
Because the status of port in neutron remains the same before and after
DF DB processed, thus no event is sent to nova.

Proposed Change
===============

Design principle
----------------

Each DF ML2 mechanism driver in neutron server subscribes a special topic.
Compute nodes publish port status update event to one of the topics. To
balance the load, compute nodes select topic randomly. Then each neutron
server will process one small portion of the port status update events.

When nova creates a VM, it will call neutron API create_port. Local
controller on compute node is notified to process the port. When the port
is online, it changes DF DB, and publishes event to notify that the port's
status has changed.

DF ML2 mechanism driver will update relative data in neutron DB on
receiving message from publisher on the specific topic.

Publisher subscriber pattern
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Port status update feature depends on the pub-sub function shown in the
following diagram. When there is a port status change, for example, nova
creates a VM which is scheduled to compute A. Publisher A will send event
with the topic(port_status_update specific). Once receiving the notification
from publisher, the subscriber in server node will invoke callback function,
and finally changes port status in neutron DB.

We need to assure that there is exactly one neutron server to process the
event and that all neutron servers will have equal chance to handle the event.

A kind of LB will be introduced. There are several neutron servers(for
example,A,B,C,D), each one will subscribe a topic, for example, neutron server
A will subscribe to topic A, neutron server B will subscribe to topic B, etc.
Each local controller will publish port status event to the topic selected
randomly.

Assuming there are 4 server nodes and 3 compute nodes. Base on the previous
description, there are 4 topics, that will be subscribed by 4 neturon servers.
Server will update its topic timestamp stored in DF DB which representing its
status. If a new server node is added to server cluster, it will add a new
topic to DF DB, and next time the compute node might publish event to that
topic.

On the other side, all compute nodes will have a random algorithm(the result
can not exceed the total number) which will select random topic stored in DF
DB to send event of port status update..

::

    +------------+     +---------+         +----+        +--------------+
    | SubscriberA <---   Topic A    <----  |    |   <----+ Publisher X  |
    +------------+     +---------+         | R  |        +--------------+
                                           | A  |
    +------------+     +---------+         | N  |        +--------------+
    | SubscriberB <---   Topic B    <----  | D  |   <----+ Publisher Y  |
    +------------+     +---------+         | O  |        +--------------+
                                           | M  |
    +------------+     +---------+         |    |        +--------------+
    | SubscriberC <---   Topic C    <----  |    |   <----+ Publisher Z  |
    +------------+     +---------+         +----+        +--------------+


The topic for port status
"""""""""""""""""""""""""
The special topic defined for port update status event is shared by all
tenants.

Pros and Cons
-------------
Pros

There are several neutron servers which will process port status
events concurrently, so it can alleviate the pressure of each server
effectively.

Cons

There is only one thread to process events published by several
compute nodes at the same time. It won't be a serious problem when
there are few nodes, but we should evaluate the process capability of
the server in detail while there are too many compute nodes, especially
when all compute nodes are online concurrently.
