
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
local or remote, where a local lport is bound to some OVS port on integration
bridge and a remote lport is bound to some OVS port on a remote machine.

This makes the controller blind to all the ports that are not bound to a
specific tap device or tunnel, such as virtual ports like router gateways,
router interfaces, FIP ports, and even compute ports on a remote machine that
are not accessed through a tunnel. This forces any consumer of those ports to
fetch them without the help of built-in syncing and change notification
facilities.

Proposed Change
===============

During the writing of this spec, there's an effort to remove ofport from
logical ports, we can utilize this to change the notion of locality for logical
ports [1]_.

We will split the ports into 3 categories:

* Local - traffic to those ports is handled by local node exclusively (except
  for optimizations like ARP responding). When some node has a packet for
  a local port on current node, it will forward it to the current node.
* Remote - those ports are local to another node. When a local node has a
  packet bound for a remote port, it will forward it to the relevant remote
  node.
* Distributed - those ports are not bound to a specific node, and each node
  can handle their traffic locally.

The classification will be done by apps, each responsible for notifying changes
of the locality of a specific port. The controller code will only emit created/
updated/deleted events, as it does for all other models.

* Classification app

 * When OvsPort is created/deleted: emit local_created/deleted event for
   referenced lport.

* DNAT app

 * When FIP is associated/disassociated locally emit local_created/deleted for
   floating lport.
 * Similarly, handle FIPs associated/disassociated remotely.

* Trunk app

 * When child segmentation is created/updated/deleted on a local trunk port,
   emit local_created/deleted events for sub-ports.
 * Similarly, handle child port segmentation events for remote trunk ports.

* L3 app

 * Emit events distributed_created/deleted for router interfaces and gateways

* DHCP app

 * (If needed) emit distributed_created/deleted on subnet create/update/delete
   events.

* Provider / tunnel apps

 * Will notify of remote_created/deleted events once flows relevant to remote
   port access are installed.

References
==========

.. [1] https://bugs.launchpad.net/dragonflow/+bug/1690775
