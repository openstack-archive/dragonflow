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

In short, we want to create a machanizm to forward traffic for example
from one VM and to forward it to another VM for the inspection. When
packet will be forwarded, the original value of source and target ip/ports
information will not be altered and the system administrator will be able
to run for example tcpdump to see these packets. The administrator, will
have to enable the promiscuous mode on the VM network card to be able to
see these packets. [#]_

In additon to tap of the VM traffic, a proposed change will also
allow to tap traffic of:

1. VM port
2. Router port
3. Virtual port

.. [#] https://github.com/openstack/tap-as-a-service

Terminology and API
-------------------

The API [#]_ defines two objects:

1. TapService

2. TapFlow

.. [#] https://github.com/openstack/tap-as-a-service/blob/master/API_REFERENCE.rst


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
        'possition': {'allow_post': True, 'allow_put': False,
                      'validate': {'type:values': possition_enum},
                      'is_visible': True}
    }

The DirectionEnum states whether the TAP is attached to the ingress,
egress, or both directions of the port.

::

    direction_enum = ['IN', 'OUT', 'BOTH']


The Possition Enum states where to place the tapping point. It can be
straight after/before mirrored port or after the application of SG
firewall rules.

::
    possition_enum = ['BEFORESG', 'AFTERSG']

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


Proposed Change
===============

In order to support Tap as a Service, a TapFlow rule can be installed in
multiple locations relative to the port:

1. Tap rule on output

2. Tap rule on input

3. Both

In addion, tapping flows can be installed before and after SG firewall rules.


Tap on the output
-----------------

In the first version, we want to intercept packets coming out of the target
port as close to the source. Flow possition in BEFORESG.

Packets arriving from VM are landed in table 0
(INGRESS_CLASSIFICATION_DISPATCH_TABLE). After marking packet's
metadata (network ID) and reg6 (source port ID)
(e.g. set_field:0x8->reg6, set_field:0x1->metadata),
the packet is transmitted to table 1 (EGRESS_PORT_SECURITY_TABLE).
In this table we verify packets and their addresses are not spoofed,
check for packets going to meta-data service, and we transfer
packets to the rest of the pipeline.

There are two main alternatives.

1. We can switch table=1 (EGRESS_PORT_SECURITY_TABLE) to
   be table=2 and install our tap rules in table=1.

   In table=1 we will add the following rules:
   ::

    Filter1:in_port=6 Actions:output(5), goto_table:2
    Filter2:any Actions: goto_table=2

2. We alter the classification rules of the VM ports in table 0 (INGRESS_CLASSIFICATION_DISPATCH_TABLE)

   Old rule:
   ::

     Filter:in_port=6 Actions:set_field:0x8->reg6,set_field:0x1->metadata,goto_table:1

   New rule:
   ::

     Filter:in_port:6 Actions:set_field:0x8->reg6,set_field:0x1->metadata,resubmit(,1),output(5)


Tap on the Input
----------------

In the first version, we want to intercept packets going to target port as
close to the destination as possible (flow possition AFTERSG). By default,
packets are forwarded to ports in table 78 (INGRESS_DISPATCH_TABLE).

In table=78 we have rules of the form:

::
  Filter:reg7=0x8 Actions:output:6

We can simply change it to:

::
  Filter:reg7=0x8 Actions:output:6,output(5)


List of relevant openflow tables
--------------------------------

INGRESS_CLASSIFICATION_DISPATCH_TABLE = 0
EGRESS_PORT_SECURITY_TABLE = 1
INGRESS_DISPATCH_TABLE = 78


TODO:
-----

1. VM on different computer nodes

2. Tap before and after SG firewall rules


References
==========

[1] https://github.com/openstack/tap-as-a-service/blob/master/API_REFERENCE.rst

[2] https://review.openstack.org/#/c/256210/9/specs/mitaka/tap-as-a-service.rst
