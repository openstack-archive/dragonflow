
..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=====================
Logical port locality
=====================

Problem Description
===================

In the current implementation, a local controller regards all lports as either
local or remote, where a local lport is bound to some ovs port on integration
bridge and a remote lport is bound to some ovs port on a remote machine.

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
  for optimizations like ARP responding). When a remote node has a packet for
  a local port on current node, it will forward it to the current node.
* Remote - those ports are local to another node. When a local node has a
  packet bound for a remote port, it will forward it to the relevant remote
  node.
* Distributed - those ports are not bound to a specific node, and each node
  can handle their traffic locally.

The classification will be done at each local controller, by a set of rules:

* Local ports:

 * All compute ports with bound ofport (and chassis = local node)
 * Trunk subports whose parent port is local
 * Floating ports whose FIP is bound to a local port
 * ... and other rules we'll require for future apps.

* Remote ports:

 * Like above, but when chassis is not local

* Distributed ports:

 * Router interfaces and gateways
 * DHCP ports
 * etc...

We should note that we don't have to classify all ports into those three
categories, the controller can ignore the ports that are not relevant to any
of the apps. To decide on the relevance, we should add (now or in future) a way
to allow customization of the rules above. Both for 3rd party apps, and our own
apps (no need to check trunk subports if trunk app is not loaded).

References
==========

.. [1] https://bugs.launchpad.net/dragonflow/+bug/1690775
