
..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=====================
Virtual logical ports
=====================

Problem Description
===================

In the current implementation, a local controller sees all lports as either
local or remote, where a local lport is bound to some tap device (via ofport)
and a remote lport is bound to some tap device on a remote machine (via the
ofport of an appropirate tunnel port).

This makes the controller blind to all the ports that are not bound to a
specific tap device, such as virtual ports like router gateways, router
interfaces, and FIP ports. This forces any consumer of those ports to fetch
them without the help of built-in syncing and change notification facilites.

Proposed Change
===============

I propose to introduce a concept of virtual ports, ports not bound to any tap
or chassis. Each app will treat (or ignore) the virtual ports as it sees fit.

The classification will be as follows:

* All ports bound to a local chassis are local
* All ports bound to any other chassis are remote
* All other ports are virtual


References
==========
