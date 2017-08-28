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


Creating a DHCP driver
======================

As part of the effort to reduce the coupling between components in
the system, this spec suggest moving all the dhpc logic from the ml2-driver
to a separate dhcp-driver.

This driver should be listen to subnet add/remove events, and create/delete
the dhcp-port according to the logic that described above.

There is 2 options listening to those events:
  * listen to neutron registry events _[1].
  * listen to dragonflow Northbound DB events _[2] 

In this spec we want to suggest that listening to dragonflow db could be
better idea - as it reduce to coupling between dragonflow and neutron
and could be a first step forward toward supporting a separate api.

References
==========
.. [1] https://docs.openstack.org/neutron-lib/latest/contributor/callbacks.html
.. [2] https://github.com/openstack/dragonflow/blob/master/doc/source/specs/nb_api_refactor.rst












