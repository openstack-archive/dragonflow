..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
TAP as a Service (TAPaaS)
=========================


Problem Description
===================

Performing network protocol review, checking firewall rules and / or
performing network security audit is part of the daily job of the system
administrator. To be able to provide this functionality in the cloud,
an idea to create a tap-as-a-service was born. For example when enabled
and configured it will allow the system administrator to run a Snort IDS
on his tenant network.

In short, we want to create a mechanism to forward traffic for example from
one VM to another. When packet will be forwarded, the original value of
source and target ip/ports information will not be altered and the system
administrator will be able to run, for example tcpdump, on the target VM to
trace these packets. The administrator, will have to enable a promiscuous
mode on the target VM network card to be able to see these packets. [1]_

Currently this document concentrates on tapping traffic coming in and out
of VMs.

Additional kinds of ports will not be supported in the first version of
the spec.

1. Tapping DHCP port
2. Tapping router port
3. Tapping floating ip traffic

Terminology and API
===================

The API [2]_ and SPEC [3]_ define two objects:

1. TapService
2. TapFlow

TapService represents the port to which the mirrored traffic is delivered.
For example this port can be attached to VM where a Snort IDS running.

::

    'tap_services': {
        'id': {'allow_post': False, 'allow_put': False,
               'validate': {'type:uuid': None}, 'is_visible': True,
               'primary_key': True},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'validate': {'type:string': None},
                      'required_by_policy': True, 'is_visible': True},
        'name': {'allow_post': True, 'allow_put': True,
                 'validate': {'type:string': None},
                 'is_visible': True, 'default': ''},
        'description': {'allow_post': True, 'allow_put': True,
                        'validate': {'type:string': None},
                        'is_visible': True, 'default': ''},
        'port_id': {'allow_post': True, 'allow_put': False,
                    'validate': {'type:uuid': None},
                    'is_visible': True},
    }


TapFlow represents the port from which the traffic needs to be mirrored.
It can be a port associated with VM on another CN.

::

    'tap_flows': {
        'id': {'allow_post': False, 'allow_put': False,
               'validate': {'type:uuid': None}, 'is_visible': True,
               'primary_key': True},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'validate': {'type:string': None},
                      'required_by_policy': True, 'is_visible': True},
        'name': {'allow_post': True, 'allow_put': True,
                 'validate': {'type:string': None},
                 'is_visible': True, 'default': ''},
        'description': {'allow_post': True, 'allow_put': True,
                        'validate': {'type:string': None},
                        'is_visible': True, 'default': ''},
        'tap_service_id': {'allow_post': True, 'allow_put': False,
                           'validate': {'type:uuid': None},
                           'required_by_policy': True, 'is_visible': True},
        'source_port': {'allow_post': True, 'allow_put': False,
                        'validate': {'type:uuid': None},
                        'required_by_policy': True, 'is_visible': True},
        'position': {'allow_post': True, 'allow_put': False,
                      'validate': {'type:values': position_enum},
                      'is_visible': True}
        'direction': {'allow_post': True, 'allow_put': False,
                      'validate': {'type:values': direction_enum},
                      'is_visible': True}
    }

The ``DirectionEnum`` states whether the TAP is attached to the ingress,
egress, or both directions of the VM port.

::

    direction_enum = ['IN', 'OUT', 'BOTH']

The ``PositionEnum`` states where to place the tapping point. It is
defined as follows:

::

    position_enum = ['VNIC', 'PORT']

VNIC specifies that the packet should be intercepted close to VM,
while PORT specifies that packet should be intercepted on the network
level.

In case we are talking about tapping outgoing packets:

  1. VNIC is before security group firewall.
  2. PORT is after security group firewall.

In case we are talking about tapping incoming packet:

  1. VNIC is after the security group firewall.
  2. PORT is before security group firewall.

Multiple TapFlow instances can be associated with a single TapService
instance. I.e. one `Snort` VM can check traffic of multiple virtual servers.

Tap packet forwarding table
===========================

After the packet is mirrored, it will be forwarded to the new packet
forwarding table (``TAP_FORWARD_TABLE``).

Packets can come from local CN and external CN. To minimize number of
changes, we propose to create a new table to handle mirrored packets.

This table may not be highly optimized, but improves the modular design.

Each mirrored packet, coming either from the same CN, or from external CN,
will have a `marked tunnel id`.

In case the packet coming from the local or external CN needs to be
forwarded locally (to the same CN), the following rules will be applied:

  ::

    filter: tun_id=DEST_TUN_ID action:output:DEST_LOCAL_PORT

In case the packet is coming from the local CN and should be forwarded
to external CN:

  ::

    filter: tun_id=DEST_TUN_ID action:output:OVERLAY_NET_PORT

  +----------------------+---------------------------------------------------------+
  |   Field Name         |  Description                                            |
  +======================+=========================================================+
  | ``DEST_TUN_ID``      |  a tunnel number will specify a destination VM          |
  +----------------------+---------------------------------------------------------+
  | ``DEST_LOCAL_PORT``  |  destination OVS port number (in case it is on same CN) |
  +----------------------+---------------------------------------------------------+
  | ``OVERLAY_NET_PORT`` |  packet will be forwarded to other CN                   |
  +----------------------+---------------------------------------------------------+

Assigning tunnel id for each TapService
---------------------------------------

Each TapService will have a unique id that corresponds to the overlay network
tunnel id.

By default, each network has it's own id called segment id allocated from neutron
segment pool. A naive approach will be to assign a unique id to be used for
TapService from this pool but we concern that admins setup network vnis and they
expects number of network to be supported.

More advance solution will be to create a new segment pool to be used exclusively
for TapServices. This new network pool should not coincide with the one used in
neutron.

In case we run out of free ids in the new segment pool, as a fallback solution,
we will assign segment id from the neutron segment pool.


Packet mirroring
================

In order to support Tap as a Service, a TapFlow packet mirroring rule
can be installed in multiple locations, relative to the port:

1. Tap rule on output

2. Tap rule on input

3. Both

In addition, tapping flows can be installed before and after SG firewall rules.


Tap on the output
-----------------

Packet can be mirrored before or after the security group firewall check.

In theory, we can add additional table and / or modify existing rules to allow
mirroring.

To make the design more modular, it was decided to add new tables instead
of altering existing rules.

Tap position is ``BEFORESG``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This configuration mode actually implies that packets will be mirrored without
filtering by security group.

Change ``table=1`` (``EGRESS_PORT_SECURITY_TABLE``) to be ``table=2`` and install our
tap rules in ``table=1``.

In new ``table=1`` we will add the following rules:

 ::

    Filter1:in_port=6 Actions:resubmit(,2),
      $DEST_TUN_ID->tun_id,goto_table:TAP_FORWARDING
    Filter2:any Actions:resubmit(,2)

In case, the source port traffic should be mirrored to multiple `TapService`:

  ::

    Filter:in_port:6 Actions:resubmit(,2),
      $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
      $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING

Tap position is ``AFTERSG``
^^^^^^^^^^^^^^^^^^^^^^^^^^^

After packets pass the firewall rules they arrive to the ``table=9``
(``SERVICES_CLASSIFICATION_TABLE``).

We should move all rules from ``table=9`` to a new table (e.g. ``table=10``).

All other tables IDs should change accordingly.

We will add new rules here:

  ::

    Filter:in_port:6 Actions:resubmit(,10),
      $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING

In case the source port traffic should be mirrored to multiple `TapService`:

  ::

    Filter:in_port:6 Actions:resubmit(,10),
      $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
      $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING

Tap on the Input
----------------

Tap position is ``AFTERSG``
^^^^^^^^^^^^^^^^^^^^^^^^^^^

After passing the firewall, packets are forwarded to ``table=78`` (``INGRESS_DISPATCH_TABLE``).

We should move all rules from ``table=78`` to a new table (e.g. ``table=79``).

We will add new rules in ``table=78``:

::

    Filter:reg7=0x8 Actions:resubmit(,79),
      $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING

In case, the source port traffic should be mirrored to multiple TapService:

::

    Filter:in_port:6 Actions:resubmit(,79),
      $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
      $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING

Tap position is ``BEFORESG``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This configuration mode actually implies that packets will be mirrored without
filtering by security group.

Before the packets pass the firewall rules they arrive to the ``table=77``
(``INGRESS_SECURITY_GROUP_TABLE``).

We should move all rules from ``table=77`` to a new table (e.g. ``table=78``)
and all other tables IDs should be updated appropriately.

We will add new rules here (``table=77``)

  ::

    Filter:in_port:6 Actions:resubmit(,78),
      $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING

In case, the source port traffic should be mirrored to multiple TapService:

  ::

    Filter:in_port:6 Actions:resubmit(,78),
      $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
      $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING,

Receiving mirrored packets from other CNs
=========================================

To be able to forward packets received from other CNs on each CN that has a
TapService we will add relevant rules to forward rules to a ``TAP_FORWARDING``
table.

We will add new rule in ``table=0``:

  ::

    Filter:tun_id=$DEST_TUN_ID1 Actions:goto_table:TAP_FORWARDING
    Filter:tun_id=$DEST_TUN_ID2 Actions:goto_table:TAP_FORWARDING

Database Changes
================

In order to support TapServices the following table will be added to
distributed nosql database.

  +--------------------+---------------------------------------------+
  |   Attribute Name   |               Description                   |
  +====================+=============================================+
  |   key              |   record identify                           |
  +--------------------+---------------------------------------------+
  |   topic            |   tenant ID                                 |
  +--------------------+---------------------------------------------+
  |   port_id          |   port id of the destination VM             |
  +--------------------+---------------------------------------------+
  |   segmentation_id  |   overlay network distinguishing tunnel id  |
  +--------------------+---------------------------------------------+

The following fields were omitted here:

 * ``name``
 * ``description``

In order to support TapFlows the following table will be added to
distributed nosql database.

  +--------------------+---------------------------------------------+
  |   Attribute Name   |               Description                   |
  +====================+=============================================+
  |   key              |   record identify                           |
  +--------------------+---------------------------------------------+
  |   topic            |   tenant ID                                 |
  +--------------------+---------------------------------------------+
  |   tap_service_id   |   id of the destination TapService          |
  +--------------------+---------------------------------------------+
  |   source_port_id   |   port id of the tapped machine             |
  +--------------------+---------------------------------------------+
  |   position         |   enum ['VNIC', 'PORT']                     |
  +--------------------+---------------------------------------------+
  |   direction_enum   |   enum ['IN', 'OUT', 'BOTH']                |
  +--------------------+---------------------------------------------+

The following fields were omitted here:

 * ``name``
 * ``description``

List of relevant OpenFlow tables
================================

::

  INGRESS_CLASSIFICATION_DISPATCH_TABLE = 0
  EGRESS_PORT_SECURITY_TABLE = 1
  SERVICES_CLASSIFICATION_TABLE = 9
  INGRESS_SECURITY_GROUP_TABLE = 77
  INGRESS_DISPATCH_TABLE = 78

References
==========

.. [1] https://github.com/openstack/tap-as-a-service
.. [2] https://github.com/openstack/tap-as-a-service/blob/master/API_REFERENCE.rst
.. [3] https://review.openstack.org/#/c/256210/
