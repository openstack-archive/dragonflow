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
Port satus update feature will enable synchronization of port status
between DF DB and neutron DB.

There is only port status in DF database updated after ports are created
currently leaving Neutron DB port status unchanged. Because of the status
of port in Neutron remains the same before and after DF DB processed, thus no
event being sent to nova.

Proposed Change
===============

Design principle
----------------

DF ML2 mechanism driver subscribe special a topic  sent by publisher from
each compute node.

When nova create a VM, it will call neutron API create_port. Local
controller on compute node is notified to process the port, then it
changes DF DB, and publishes event at last.

DF ML2 mechanism driver will update relative data in Neutron DB afer
get message from publisher with the specific topic.

Publisher subscriber pattern
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Port status update feature depends on the sub-pub function shown in the
following diagram. When there is a port status change, for example, nova
create a VM which scheduled to compute A. Publisher A will send event
with the topic(port_status_update specific).On receiving an event from
publisher, the subscriber in server node will invoke callback function,
and finally change port status in neutron DB.

We need to consider that there is only one neutron server to process the
event simultaneously and that all neutron servers will have equal chance
to handle the event.

A kind of LB will be introduced. There are several topics(A,B,C,D...),to
which each neutron server will subscribe, for example, neutron server A
will subscribe to topic A, neutron server B will subscribe to topic B, etc.
Each local controller will publish different topic according to the result
of processing its HostID or something else.

It is assumed that there are 4 server nodes and 400 compute nodes. Base on
the previous description, there are 4 topics, A for node1, B for node2, C
for node3, and D for node4. At the side of compute nodes, we need to have
a MOD function MOD(number, divisor), parameter number meaning dividend, and
parameter divisor here of course meaning divisor. Finally compute node 1,5,
9,13...will send event to server A, and compute nodes 2,6,10,14...will send
event to server B, etc.

Actually, here the parameter number of MOD might be int(compute node IP),
and divisor might be actual number of server node. So in this case, we can
ignore the impact of increasing or decreasing compute node.

                                       +--------------+
                                  <----+ Publisher A  |
                                  |    +--------------+

+------------+   |    +---------+ <----+--------------+
| Subscriber <---+      Topic A  +  +  | Publisher B  |
+------------+   |    +---------+ <----+--------------+

                                  |    +--------------+
                                  <----+ Publisher C  |
                                       +--------------+

The topic for port status
"""""""""""""""""""""""""
A special topic defined for port update status event is shared by all tenants.

Pros and Cons
-------------
Pros

Neutron server performance would be considered while there are lots of
publishers on each compute node and only several subscribers in the server
node.

There are rarely changes to the previous architecture, because of the
decoupling between server and compute node while using pub-sub function.

Cons

There is only one thread to process events being published from several
compute nodes at the same time. Its will not have a serious problem when
there are a few nodes, but we should evaluate the process capability of
the server in detail while there are too many compute nodes, especially
when all compute nodes are online concurrently.

We must guarantee that the compute nodes should perceive status(down/up)
of server node to which it send event immediately, and rapid recovery of
accessibility between server node and compute node if failure occurs.
