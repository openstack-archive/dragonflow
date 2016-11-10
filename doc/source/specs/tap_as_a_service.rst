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
and configured it will allow the system administrator to run a SNORT IDS
on his tenant network.

In short, we want to create a machanism to forward traffic for example
from one VM and to forward it to another VM for the inspection. When
packet will be forwarded, the original value of source and target ip/ports
information will not be altered and the system administrator will be able
to run for example tcpdump to trace these packets. The administrator, will
have to enable the promiscuous mode on the VM network card to be able to
see these packets. [#1]_

In additon to tap of the VM traffic, a proposed change will also
allow to tap traffic of:

1. VM port
2. Router port
3. Virtual port

Terminology and API
-------------------

The API [#2]_ defines two objects:

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
        'direction': {'allow_post': True, 'allow_put': False,
                      'validate': {'type:values': direction_enum},
                      'is_visible': True}
        'position': {'allow_post': True, 'allow_put': False,
                      'validate': {'type:values': position_enum},
                      'is_visible': True}
    }

The DirectionEnum states whether the TAP is attached to the ingress,
egress, or both directions of the port.

::

    direction_enum = ['IN', 'OUT', 'BOTH']


The position Enum states where to place the tapping point. It can be
straight after/before mirrored port or after the application of SG
firewall rules.

::
    position_enum = ['BEFORESG', 'AFTERSG']

Multiple TapFlow instances can be associated with a single TapService
instance. So, one Snort VM can check traffic of multiple virtual servers.


Unrolling packet cycles
-----------------------

When a system administrator configures the system perform a tap of the tap VM
in some cases it can create a situation where he receives duplicate packets.
We can prevent this by unrolling the rules. Consider the following scenario:

::
   [A]----+-->[T1]-+
          |        +->[T2]
   [B]----+        |
                   |
   [C]-------------+

Where: T1 taps A,B
       T2 taps A, C and T1
We can reduce this scenario to:
       T1 taps A, B
       T2 taps A, B, C

What we have to do is basically construct a directed graph of ports,
(edges from TapFlow port to TapService port), make sure it is acyclic,
flip the edges, then for each TapService port, it should tap all the
reachable ports in the graph.

This basically makes sure that all the tapping is depth one. The only downside
is that it has to be recalculated each time tapping topology changes.


Mirrored packet forwarding table
================================
After the packet is mirrored, it will be forwarded to the new packet
forwarding table.

Packets can came from local CN and from external CN. To minimize number of
changes, I suggest to create a new table to handle mirrored packets.

This table will not be hightly optimized but will more suitable for modular
design.

Each mirrored packet, comming from the same CN or from external CN will
have a marked tunnel id.

In case the packet is comming from the local or external CN and it should
be forwarded locally the following kind of rules will be created:

  ::
    filter: tun_id=DEST_TUN_ID action:output:DEST_LOCAL_PORT

In case the packet is comming from the local CN and should be forwarded
to external CN:

  ::
    filter: tun_id=DEST_TUN_ID action:output:OVERLAY_NET_PORT

Where

  ::
    DEST_TUN_ID - a tunnel number will specify a desttination VM
    DEST_LOCAL_PORT - destination ovs port number (in case it is on same CN)
    OVERLAY_NET_PORT - packet will be forwarded to other CN


Assigning tunnel id for each TapService
---------------------------------------
Each TapService will have a unique tunnel id. These unique ids should be saved
in distibuted database.


Packer mirroring
================
In order to support Tap as a Service, a TapFlow packet mirroring rule
can be installed in multiple locations relative to the port:

1. Tap rule on output

2. Tap rule on input

3. Both

In addion, tapping flows can be installed before and after SG firewall rules.


Tap on the output
=================

Packet can be mirrored before or after the security group firewall check.

Depending of design we can add aditional table and / or modify existing
rules to allow mirroring. To minimize number of changes I prefer to alter
existing rules.

Tap position is BEFORESG
------------------------

Changes in table 0 (INGRESS_CLASSIFICATION_DISPATCH_TABLE)

Old rule:
  ::

    Filter:in_port=6 Actions:set_field:0x8->reg6,set_field:0x1->metadata,goto_table:1

New rule:
  ::

    Filter:in_port:6 Actions:set_field:0x8->reg6,set_field:0x1->metadata,resubmit(,1),
                              $DEST_TUN_ID->tun_id,goto_table:TAP_FORWARDING

In case, the source port traffic should me mirrored to multiple TapService:
  ::

    Filter:in_port:6 Actions:set_field:0x8->reg6,set_field:0x1->metadata,resubmit(,1),
                             $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
                             $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING,

Tap position is AFTERSG
-----------------------

After packets pass the firewall rules they arrive to the table 9. We should move all
rules from table 9 to a new table (for example 10) and all other table' ids should be
increased respectivly.

We will add new rules here:
  ::

    Filter:in_port:6 Actions:resubmit(,11),
                             $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING

In case, the source port traffic should me mirrored to multiple TapService:
  ::

     Filter:in_port:6 Actions:resubmit(,11),
                              $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
                              $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING,


Tap on the Input
================

Tap position is AFTERSG
-----------------------

After passing firewall packets are forwarded to table 78 (INGRESS_DISPATCH_TABLE).

In table=78 we have rules of the form:

::
  Filter:reg7=0x8 Actions:output:6

We can simply change it to:

::
  Filter:reg7=0x8 Actions:output:6,
                          $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,

In case, the source port traffic should me mirrored to multiple TapService:
  ::

     Filter:in_port:6 Actions:output(6),
                              $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
                              $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING,


Tap possition is BEFORESG
-------------------------

Before the packets pass the firewall rules they arrive to the table 77
(INGRESS_SECURITY_GROUP_TABLE). We should move all rules from table 77 to a new
table (for example 78) and all other table' ids should be increased respectivly.

We will add new rules here (table 77)
  ::

    Filter:in_port:6 Actions:resubmit(,78),
                             $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING

In case, the source port traffic should me mirrored to multiple TapService:
  ::

     Filter:in_port:6 Actions:resubmit(,78),
                              $DEST_TUN_ID1->tun_id,goto_table:TAP_FORWARDING,
                              $DEST_TUN_ID2->tun_id,goto_table:TAP_FORWARDING,


Receving mirrored packets from other CNs
========================================

To be able to forward packets received from other CNs on each CN that has a
TapService we will add relevant rules to forward rules to a TAP_FORWARDING
table.

We will add new rule in table 0:

  ::
    Filter:tun_id=$DEST_TUN_ID1 Actions=set_field:0x1->metadata,goto_table:TAP_FORWARDING
    Filter:tun_id=$DEST_TUN_ID2 Actions=set_field:0x1->metadata,goto_table:TAP_FORWARDING


List of relevant openflow tables
--------------------------------

INGRESS_CLASSIFICATION_DISPATCH_TABLE = 0
EGRESS_PORT_SECURITY_TABLE = 1
SERVICES_CLASSIFICATION_TABLE = 9
INGRESS_SECURITY_GROUP_TABLE = 77
INGRESS_DISPATCH_TABLE = 78


TODO:
-----

1. Database schema changes


References
==========

[1] https://github.com/openstack/tap-as-a-service

[2] https://github.com/openstack/tap-as-a-service/blob/master/API_REFERENCE.rst

[3] https://review.openstack.org/#/c/256210/9/specs/mitaka/tap-as-a-service.rst
