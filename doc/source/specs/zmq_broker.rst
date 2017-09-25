..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

====================================
Example Spec - The title of your RFE
====================================

Work will be tracked under the following bug:

https://bugs.launchpad.net/dragonflow/+bug/1716933

This feature discusses the removal of _multiproc_ publishers, and allow only
_broker_ publishers, i.e. publisher's which have a broker service (e.g. redis).

In order to support full pluggability, it is also proposed to add a ZMQ-based
broker implementation.


Problem Description
===================

Our _multiproc_ pub/sub mechanism is proving to not work as well as it should.

_multipoc_ means that we run a process per controller node (which
contains the neutron server), which binds the network socket and sends
the events. The neutron servers (forked one per cpu) connect to that
service via IPC (read unix socket) and send the events to it.  In essence,
it is a publisher proxy.

In essence, this solution is reducible to our current pub/sub solution. But
we won't use that reduction, because we want to support active_port_detection
and the neutron notifier (which should be rewritten as well, but that's orthogonal)

At the end of the day, in the Dragonflow scheme of things, a brokerless
solution just doesn't work. We see that since from the get-go (almost)
we hacked around it by making a 'multiproc' publisher.

This is especially noticeable when we want to publish messages from
compute nodes (running the Dragonflow local controller) as well,
e.g. neutron notifier only works with Redis. On standalone machines
(both server and compute), we see port binding collisions.

Open question:

 * How do we make it truly distributed?

 * If and How do we do broker-side filtering?

 * It is preferable to use an out-of-tree, existing solution. Which one to take?

 * How to integrate with devstack (Not exactly an open question, but should be
   part of the implementation)

Proposed Change
===============


We propose to design a way for the ZMQ driver to be a broker. e.g. write
a ZMQ-based pub/sub broker. Neutron server (the 'publishers') connect
with a PULL/PUSH socket - that's the pattern for many publishers, few
subscribers. The subscribers connect with a PUB/SUB socket - that's the
pattern for many subscribers, few publishers.

There are many interesting ideas in this regard in [1]_.

TBD


References
==========

.. [1] http://zguide.zeromq.org/page:all
