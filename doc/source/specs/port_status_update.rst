This work is licensed under a Creative Commons Attribution 3.0 Unported
License.

http://creativecommons.org/licenses/by/3.0/legalcode

===================
Port status update
===================

https://blueprints.launchpad.net/dragonflow/+spec/allowed-address-pairs

This blueprint describes how to support port status update for
Dragonflow.

Problem Description
=====================
Port satus update feature will enable synchronization of port sutatus
between DF db and neturon DB.

There is only port status in DF database updated after ports are created,
leaving Neutron DB port status unchanged.Because of the status of port
in Neutron being same before and after DF db processed, thus no event
sent to nova.

Proposed Change
===============

Design principle
----------------

The pricinple is very simple:

DF ML2 mechanism driver subscribe special topic which is sent
by publisher from each compute node

When nova create a vm, it will call neutron API create_port. local
controller on compute node is notified to process the port, and after
that, it changes DF db, then publishes event

DF ML2 mechanism driver will update relative data in Neutron db afer
get message from publisher with the specific topic.

Publisher subscriber pattern
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Port status update feature depends on the sub-pub function shown in the
following diagram. When there is a port status change, for example, nova
create a vm which scheduled to compute A. Publisher A will send event
with the topic(port_status_update specific).On receiving an event from
publisher, the subscriber in server node will do callback function, and
finally change port status in neutron db.

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
A special topic defined for port update status event shared by all tenants.

Pros and Cons
-------------
Pros

Neutron server perfermance would be considered while there are lots of
publishers on each compute node and only several subscribersin server node

Cons

There are rarely chagnes to the previous architecture, because of using
pub-sub function.

