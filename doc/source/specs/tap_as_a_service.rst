..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
TAP as a Service (TAPaaS)
=========================


Problem Description
===================

Tap device is intended for the tenant admin to perform network tracing
for example for security purposes. The administrator will be able to
run Snort IDS on one of his VMs and intercept traffic from all hist
other hosts and routers, etc.. For this purpose we want to add 
tap-as-a-service for the Dragonflow. [#]_

.. [#] https://github.com/openstack/tap-as-a-service


Terminology and API
-------------------

The API [#]_ defines three objects:

1. TapService

2. TapFlow

3. direction_enum

.. [#] https://github.com/openstack/tap-as-a-service/blob/master/API_REFERENCE.rst 


TapService represents the port on which the mirrored traffic is delivered.
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
    }

DirectionEnum states whether the TAP is attached to the ingress, egress, or
both directions of the port.

::

    direction_enum = ['IN', 'OUT', 'BOTH']


Multiple TapFlow instances can be associated with a single TapService
instance. So, one Snort VM can check traffic of multiple virtual servers.


Proposed Change
===============

In order to support Tap as a Service, a TapFlow rule can be installed in
multiple locations relative to the port:

1. Tap rule on output

2. Tap rule on input

3. Both


Tap on the output
-----------------

We want to intercept packets coming out from the VM as close
to the source. Packets arriving from VM are landed in table
0 (INGRESS_CLASSIFICATION_DISPATCH_TABLE). After marking
packet's metadata (network ID) and reg6 (source port ID)
(e.g. set_field:0x8->reg6,set_field:0x1->metadata), the packet is
transmitted to table 1 (EGRESS_PORT_SECURITY_TABLE). In this table we
verify packets and their addresses are not spoofed, check for packets
going to meta-data service, and we transfer packets to the rest of the
pipeline.

There are two main alternatives.

1. We can switch table=1 (EGRESS_PORT_SECURITY_TABLE) to
   be table=2 and install our tap rules in table=1.

   In table=1 we will add the following rules:

::

    Filter1:in_port=6 Actions:output(5), goto_table:1
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

We want to intercept packets going to the VM as close to the destination as possible.
Packets are outputted to ports in table 78 (INGRESS_DISPATCH_TABLE).

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

2. Tap of the tap (TapFlow of the TapService).


References
==========

[1] https://github.com/openstack/tap-as-a-service/blob/master/API_REFERENCE.rst 
