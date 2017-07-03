
..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=====================
Logical port locality
=====================

Problem Description
===================

In the current implementation, a local controller sees all lports as either
local or remote, where a local lport is bound to some tap device (via ofport)
and a remote lport is bound to some tap device on a remote machine (via the
ofport of an appropirate tunnel port).

This makes the controller blind to all the ports that are not bound to a
specific tap device or tunnel, such as virtual ports like router gateways,
router interfaces, FIP ports, and even compute ports on remote machine that are
not accessed through a tunnel. This forces any consumer of those ports to
fetch them without the help of built-in syncing and change notification
facilites.

Proposed Change
===============

During the writing of this spec, there's an effort to remove ofport from
logical ports, we can utilize this to change the notion of locality for logical
ports [1]_.

We will split the ports into 3 categories:

* Local - traffic to those ports is handled by local node exclusively (except
  for optimizations like ARP responding), other hosts will forward traffic of
  bound to this port to the local
* Remote - those ports are local to another node, and their traffic should be
  forwarded.
* Distributed - those ports are not bound to a specific node, and each node
  can handle their traffic locally

The classification will be done at each local controller, by a set of rules:

* Local ports:

 * All compute ports with bound ofport (and chassis = local node)
 * Trunk subports whose parent port is local
 * Floating ports whose FIP is bound to a local port
 * ... and other rules we'll require for future apps.

* Remove ports:

 * Like above, but when chassis is not local

* Distributed ports:

 * Router interfaces and gateways
 * DHCP ports
 * etc...

We should note that we don't have to classify all ports into those three
categories, we can ignore the ports that are not relevant to any of the apps.

We should add (now or in future) a way to allow 3rd party code to customize
the classification in case our own rules don't fit the 3rd party apps.

References
==========

.. [1] https://bugs.launchpad.net/dragonflow/+bug/1690775
