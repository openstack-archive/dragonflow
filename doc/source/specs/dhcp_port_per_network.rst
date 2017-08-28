=====================
DHCP port per network
=====================

Problem Description
===================

Currently dragonflow create one dhcp-port per enable-dhcp-subnet.

As DF don't save information about packet subnet in the ovs metadata/registers,
For forwarding the packets toward the dhcp-port it's need to install flow for
each VM in the subnet.

This behaviour cause complexity in the code, that because every change in subnet
(updated/add/delete/enabled-dhcp/disabled-dhcp) raise the need to do diff with
the previous state, and install/remove all relevant flows.

Proposed Change
===============

Instead creating dhcp-port per subnet , DF will create one lport per
enabled-dhcp switch (when enabled-dhcp-switch defined as switch that
have at least one enable-dhcp-subnet).

In this case we can use one flow per lswitch for foward the packet
to controller, as lswitch information saved in the OXM_OF_METADATA.

In the app the subnet of the packets will be identify by the lport
that is known by reg6.

Packets that belong to subnet that not enabled dhcp will be dropped.

Advantage of that change:

* Remove the code complication that described above

* Reduce mumber of flows in dhcp tables

* Reduce the number of lport in the DB













