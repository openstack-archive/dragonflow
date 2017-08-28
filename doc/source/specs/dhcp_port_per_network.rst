=====================
DHCP port per network
=====================

Problem Description
===================

Currently dragonflow creates one dhcp-port per enable-dhcp-subnet.

DF does not save information about packet subnet in the ovs metadata/registers.
For forwarding packets toward the dhcp-port its needs to install flow for
each port in the subnet.

This behaviour causes complexity in the code and create a performance penalty,
that because every change in subnet (updated/add/delete/enabled-dhcp/disabled-dhcp)
raises the need to do diff with the previous state, and install/remove all relevant flows.

Proposed Change
===============

Instead of creating dhcp-port per subnet, DF will create one port per
enabled-dhcp network (when enabled-dhcp-network defined as a network that
have at least one enable-dhcp-subnet).

This port will contain multiple ips - one for each dhcp subnet that
connected to the port. All port CUD operation will done with neutron
plugin for using it's ip-address-managemnt.

Neutron data-model impact
-------------------------
Instead of one dhcp logical port subnet, there will be
one dhcp-port per network.That port will hold the ips
from all enabled_dhcp subnets that belong that network.

Dragonflow data-model impact
----------------------------
Instead dhcp-lport per logical-subnet, there will be dhcp-port
per logical-switch. enable_dhcp trait will be removed from logical-subnet.

Dragonflow controller impact
----------------------------
For forwarding the dhcp requests to the controller - the dhcp-app will install
one flow per lswitch (The lswitch can be identified in the ovs tables
by the OXM_OF_METADATA field).

when packets arrived to the dhcp-app,  the subnet of the packets
will be identified by the lport (that information stored in reg6).
Packets that belong to subnet that not enabled dhcp will be dropped.

Advantage of that change
------------------------

* Remove the code complication that described above

* Reduce mumber of flows in dhcp tables

* Reduce the number of lport in the DB


Separate the DHCP logic
=======================

As part of the effort to reduce the coupling between components in
the system, this spec suggest moving all the dhpc-logic from the
mech_driver code to a separate code module.

This module will be invoked by the ml2-driver, and will function
independently. It's will used by neutron registry _[1] for subscribing
to sunbet and lswitch CUD event's, and will be responsible for maintain
the dhcp-port according to the logic that described above.


References
==========
.. [1] https://docs.openstack.org/neutron-lib/latest/contributor/callbacks.html













