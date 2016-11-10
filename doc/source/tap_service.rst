Devstack tap as a service
-------------------------

Tap device is intended for the tenant admin to perform network tracing
for example for security purposes. The administrator will be able to
run Snort IDS on VMs in his network - everything in cloud. For this 
purpose we want to add tap-as-a-service for the Dragonflow.


Some terminology:


TapService represents the port on which the mirrored traffic is delivered.
For example this port can be attached to VM where a Snort IDS running.

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

direction_enum = ['IN', 'OUT', 'BOTH']


Multiple TapFlow instances can be associated with a single TapService
instance. So, one Snort VM can check traffic of multiple virtual servers.

TapFlow rule can be installed in multiple locations in openflow:
1. Tap rule on output
2. Tap rule on input


1. Tap on the output
--------------------
We want to intercept packets coming out from the VM as close to the
source. Packets arriving from VM are landed in table 0 
(INGRESS_CLASSIFICATION_DISPATCH_TABLE). After marking packet with
(set_field:0x8->reg6,set_field:0x1->metadata) packet is transmitted
to table 1 (EGRESS_PORT_SECURITY_TABLE). In this table we check for
packets going to meta-data service, and we transfer packets to other
rules and flows. We must add our tapping rule here. 

We have a number of alternatives here
-------------------------------------
We can switch table=1 (EGRESS_PORT_SECURITY_TABLE) from table=1 to
be table=2 and install our tap rules in table=1.

In table=1 we will add the following rules:

  Filter1:in_port=6 Actions:output(5), goto_table:1
  Filter2:any Actions: goto_table=2


Another alternative, is to alter rule as VM port is added to the
openflow rules.

Old rule:
  Filter:in_port=6
  Actions:set_field:0x8->reg6,set_field:0x1->metadata,goto_table:1
New rule:
  Filter:in_port:6
  Actions:set_field:0x8->reg6,set_field:0x1->metadata,resubmit(,1),
          output(5)

2. Tap the input
----------------
In table=78 (INGRESS_DISPATCH_TABLE) we have rules:

  Filter:reg7=0x8 Actions:output:6

We can simply change it to:

  Filter:reg7=0x8 Actions:output:6,output(5)


TODO:
-----
1. VM on different computer nodes
2. Tap of the tap (TapFlow of the TapService).


List of relevant openflow tables
--------------------------------

INGRESS_CLASSIFICATION_DISPATCH_TABLE = 0
EGRESS_PORT_SECURITY_TABLE = 1
INGRESS_DISPATCH_TABLE = 78
