..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===============================
Distributed DNAT Implementation
===============================

https://blueprints.launchpad.net/dragonflow/+spec/fip-distribution

The above blueprint describes how to implement distributed DNAT
in Dragonflow. As a supplement, this spec will describe the work
flow further and introduce a solution to learn external gateway mac
dynamically.

Proposed Change
===============
In the proposed blueprint, it suggests use br-ex to manage the DNAT
openflow rules. It means the local Drgonflow controller need manage
two or multiple openvswitch bridges. Considering some user may use
themselves bridges, it's better to focus all the common features on
the common br-int bridge.The br-ex or other br-xxx just forward the
traffic to patch port or physical port. So DNAT will be implemented
on the br-int.

In addition, a dynamical learning external gateway mac address
solution will be introduced also.

Implementation
===============
Work flow Description
---------------------
There are several related use cases with distributed virtual router.
1. The initialization of external bridge
As current Neutron external network, tenant network is connected with
external network by a external bridge. So the local Dragonflow
controller need to create this external bridge by parse the
configuration file. eg, the configuration file items

external_network_bridge = br-ex
gateway_external_network_id = 
::
    +--------------+                 +--------------+
    |df controller |                 | ovs(vswitchd)|
    |              |                 |              |
    +------+-------+                 +-------+------+
           |                                 |
           |                                 |
           +----+                            |
           |    | Parse the external network |
           |    | configuration              |
           |    |                            |
           |<---+                            |
           |                                 |
           |Create external network bridge and
           |attach the patch port to the br-int
           +-------------------------------->+----+Create bridge
           |                                 |    |and patch port
           |                                 |    |
           |                                 |<---+
           |  Report patch port on the br-int|
           |<--------------------------------+
           +---+                             |
           |   |Save patch port              |
           |<--+                             |
           |                                 |
           |                                 |
           |                                 |
           +                                 +

2. Associate a floating ip for a tenant VM
Dragonflow controller will monitor the VM port [1], once receive
the port online event, it will subscribe this port assoicate/dis-
associate floating ip topics [2].
Once user create a floating ip for a vm, DFPlugin will publish
this topic. Then the Drgonflow controller will receive this event
and get the floating ip information, and generate a serial flow
rules.
a) Create floating ip and install arp responder flow rules
::
    +--------------+     +------------+  +------------+   +-------------+   +-----------+
    |Neutron-Server|     |Pub|sub     |  |Distributed |   |df controller|   |ovs(vswitchd
    |/Plugin       |     |Server      |  |db          |   |             |   |ovsdb)     |
    +------+-------+     +------+-----+  +-----+------+   +-------------+   +-----+-----+
           |                    |              |                 +vm port status  |
           |                    |              |                 |report          |
           |                    |              |                 |<---------------+
           |                    |              |                 +--+             |
           |                    |              |                 |  |Save to db   |
           |                    |              |                 |  |and local cache
           |                    | Subscribe this port floating   +<-+             |
Create a   |                    | ip info      |                 |                |
floating ip|                    |<-------------------------------+                |
+--------->+--+DFPlugin/ml2 plugin             |                 |                |
           |  |df driver write  |              |                 |                |
           |  |the configration |              |                 |                |
           |<-+                 |              |                 |                |
           |   Write the floating info to dist-db                |                |
           +--------------------+------------->|                 |                |
           |                    |              |                 |                |
           |                    |              |                 |                |
           |Publish the floating|              |                 |                |
           |ip topic of this port              |                 |                |
           +------------------->|              |                 |                |
           |                    |              |                 |                |
           |                    | Notify the floating ip topic   |                |
           |                    +--------------+---------------->|                |
           |                    |              | Fetch the floating               |
           |                    |              | ip info         +                |
           |                    |              |<-------------------+generate the |
           |                    |              |                 |  |flow rules   |
           |                    |              |                 |  |for this     |
           |                    |              |                 |<-+floating ip  |
           |                    |              |                 |                |
           |                    |              |                 |Install an arp responder
           |                    |              |                 |flow rules on br-int
           |                    |              |                 |for this floating ip
           |                    |              |                 +--------------->|
           |                    |              |                 |                |
           |                    |              |                 |                |
           +                    +              +                 +                +

b) Install external gw arp reply packet in flow rule to get the
external gateway mac address. and then install DNAT flow rules. 
In order to learn external gw mac, Dragonflow controller should
parse the arp request packet.
::
+---------------+    +----------------+    +--------------+
|df controller  |    | ovs(vswitchd   |    |external gw   |
|               |    | ovsdb)         |    |              |
+------+--------+    +--------+-------+    +------+-------+
       |                      |                   |
       |Install a flow rule to|                   |
       |receive the external  |                   |
       |gw arp reply.         |                   |
       +--------------------->|                   |
       |                      |                   |
       |                      |                   |
       |                      |                   |
       |Send a packet out for |                   |
       |external gw arp request                   |
       +--------------------->|                   |
       |                      | arp request       |
       |                      +------------------>|
       |                      |                   |
       |                      |                   |
       |                      |  arp reply        |
       |                      |<------------------+
       |                      |                   |
       | Packet in event for  |                   |
       | external gw arp reply|                   |
       |<---------------------+                   |
       +----+                 |                   |
       |    | generate DNAT   |                   |
       |    | flow rules      |                   |
       |    |                 |                   |
       |<---+                 |                   |
       | Install DNAT flow    |                   |
       | rules on br-int      |                   |
       +--------------------->|                   |
       |                      |                   |
       |Install forwarding flow                   |
       |rules                 |                   |
       +--------------------->|                   |
       +                      +                   +

3. The external gw arp update
If the external gateway mac address changed, it will send a
gratuitous arp, Dragonflow controller will parse this packet
and update DNAT flow rules.
::
+---------------+    +----------------+    +--------------+
|df controller  |    | o^s(vswitchd   |    |external gw   |
|               |    | o^sdb)         |    |              |
+------+--------+    +--------+-------+    +------+-------+
       |                      |                   |
       |                      |                   |
       |                      | Gratuitous arp    |
       |                      |<------------------+
       |                      |                   |
       | Packet in e^ent for  |                   |
       | gw Gratuitous arp    |                   |
       |<---------------------+                   |
       +----+Parse the gratuitous                 |
       |    |arp, if gw mac address               |
       |    |is updated, update                   |
       |    |the Egress table +                   |
       |<---+                 |                   |
       | Install DNAT flow    |                   |
       | rules on br-int      |                   |
       +--------------------->|                   |
       +                      +                   +

4. Disassociate a floating ip from a port
Similarly, once user update or delete a floating ip for a vm,
DFPlugin will publish this topic. Then the Drgonflow controller
will receive this event and remove relevant flow rules.
::
     +--------------+     +------------+  +------------+   +-------------+   +-----------+
     |Neutron+Server|     |Pub|sub     |  |Distributed |   |df controller|   |ovs(vswitchd
     |/Plugin       |     |Ser^er      |  |db          |   |             |   |ovsdb)     +
     +------+-------+     +------+-----+  +-----+------+   +------+------+   +-----+-----+
            |                    |              |                 |                |
delete/update                    | ip info      |                 |                |
floating ip |                    +<-------------------------------+                |
 +--------->+--+DFPlugin/ml2 plugin             |                 |                |
            |  |df driver write  +              |                 |                |
            |  |the configration |              |                 |                |
            |<-+                 +              +                 |                |
            |   Write the floating info to dist+db                |                |
            +--------------------+------------->+                 |                |
            |                    |              |                 |                |
            |                    |              |                 |                |
            |Publish the floating+              |                 |                |
            |ip topic of this port              |                 |                |
            +------------------->+              |                 |                |
            |                    |              +                 |                |
            |                    | Notify the floating ip topic   |                |
            |                    +--------------+---------------->+                |
            |                    |              |                 |                |
            |                    |              |                 |Delete the arp  |
            |                    |              |                 |responder flow  |
            |                    |              |                 |rules           |
            |                    |              |                 +--------------->+
            |                    |              |                 |                |
            |                    |              |                 |                |
            |                    |              |                 |Delete DNAT flow|
            |                    |              |                 |rules           |
            |                    |              |                 +--------------->+ 
            |                    |              |                 |                |
            |                    |              |                 |Delete forwarding
            |                    |              |                 |flow rules      |
            |                    |              |                 +--------------->|
            |                    |              |                 |                |
            +                    +              +                 +                +

DNAT Pipeline
--------------
VM egress pipeline
******************

L3 Lookup process will distinguish the north-south traffic,
and then commit into 'Egress NAT' table to do the DNAT
processing.
::
+----------+       +------------+     +------------+   +------------+
|   VM     |       | L3 Lookup  |     | Egress NAT |   | External   |
|          +-...+-->            +----->            +---> network    |
+----------+       +------------+     +------------+   +------------+
1. Distinguish the north-south traffic
table=L3_LOOKUP_TABLE,priority=0,actions=submit(,EGRESS_NAT_TABLE)

2. DNAT processing, change source mac into floating gateway mac,
change destination mac into external gateway mac, and change
source ip into floating ip.
table=EGRESS_NAT_TABLE,dl_dst=fip_gw_mac,ip,nw_src=vm_ip,
      actions=mod_dl_src=fip_gw_mac,mod_dl_dst=ext_gw_mac,
              mod_nw_src:fip,output:gw_patch_port

External network ingress pipeline
*********************************
::

                                             +----------------+
                                             | FIP arp        |
                                      +-----^+ Responder      |
                                      |      +----------------+
                                      |
                                      |
+----------+    +---------------+     |      +----------------+            +---------------+
|External  |    |Ingress        |     |      | Ingress DNAT   |            | Ingress       |
|network   +-...^classification +------------> Processing     +------------> Dispatch      |
+----------+    +---------------+     |      +----------------+            +---------------+
                                      |
                                      |
                                      |      +----------------+
                                      |      |external gw arp |
                                      +------>packet in       |
                                             +----------------+
1. If the traffic come from the gateway patch port, it
will be committed to INGRESS_NAT_TABLE for further processing
table=INGRESS_CLASSIFICATION_DISPATCH_TABLE,in_port=gw_patch_port,
     actions=submit(0, INGRESS_NAT_TABLE)

2. The external traffic will be classified again
1). A arp responder rule will be installed to response
floating ip arp request.
ARP_RESPONDER_ACTIONS = ('move:NXM_OF_ETH_SRC[]->NXM_OF_ETH_DST[],'
                         'mod_dl_src:%(mac)s,'
                         'load:0x2->NXM_OF_ARP_OP[],'
                         'move:NXM_NX_ARP_SHA[]->NXM_NX_ARP_THA[],'
                         'move:NXM_OF_ARP_SPA[]->NXM_OF_ARP_TPA[],'
                         'load:%(mac)#x->NXM_NX_ARP_SHA[],'
                         'load:%(ip)#x->NXM_OF_ARP_SPA[],'
                         'in_port')
table=INGRESS_NAT_TABLE,arp,arp_tpa=fip,
      actions=ARP_RESPONDER_ACTIONS % ('mac'=fip_gw_mac, 'ip'=fip)

2) A rule which packet in gateway arp reply will be
installed. Dragonflow controller will learning external
gateway mac address from the arp rely packet.
table=INGRESS_NAT_TABLE,arp,arp_tpa=ext_gw_ip,actions=controller

3) A rule which packet in gateway gratuitous arp will be
installed. Dragonflow controller will learn the updation
of the external gateway mac address..
table=INGRESS_NAT_TABLE,arp,dl_dst=ff:ff:ff:ff:ff:ff,arp_spa=ext_gw_ip,
      actions=controller

4) A DNAT rule will be installed. It will change the
source mac into fip gateway mac and change the source
destination into vm ip address. Then commit into
INGRESS_DISPATCH_TABLE for further processing.
table=INGRESS_NAT_TABLE,ip,nw_dst=fip,actions=mod_nw_dst:vm_ip,
      mod_dl_src=fip_gw_mac,submit(,INGRESS_DISPATCH_TABLE)

References
==========
[1] https://review.openstack.org/#/c/274332/7/doc/source/specs/ovsdb_monitor.rst
[2] https://blueprints.launchpad.net/dragonflow/+spec/pubsub-module
