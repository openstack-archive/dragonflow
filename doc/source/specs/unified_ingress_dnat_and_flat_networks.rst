..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==========================================
Unify ingress DNAT and flat network handling
==========================================

https://blueprints.launchpad.net/dragonflow/+spec/unify-dnat-flat


Problem Description
===================

When using flat network (e.g. a port on the public network), we add a rule from
INGRESS_CLASSIFICATION_DISPATCH_TABLE(0) to INGRESS_DESTINATION_PORT_LOOKUP_TABLE(7)
when there's a packet not tagged with vlan (and does not match other egress rules)

table=0, .. priority=50,vlan_tci=0x0000/0x1fff actions=load:0x2->OXM_OF_METADATA[],resubmit(,7)


Additionally, when using floating IPs bound to local ports, we forward all
traffic from the external interface to INGRESS_NAT_TABLE(15)

table=0, .., priority=1,in_port=1 actions=resubmit(,15)

The use of ports on flat networks causes the DNAT rule to be shadowed thus
floating IP not accessible on the controller.

Proposed Change
===============

Until actual lookup in the list of floating IPs, it is impossible to tell apart
a floating IP from an address allocated on the public network, as those are
often allocated from the same pool.

To dispatch both successfully I propose to handle both in the same table.

Option 1
~~~~~~~~
Route all external traffic to INGRESS_DESTINATION_PORT_LOOKUP_TABLE(7) 
(incl. DNAT) and install DNAT flows in this table, with this change we might
want to rename the table to better reflect its purpose.

   +---------+                  +------------+
   | Table 0 |                  |  Table 7   |
   |         | vlan=X/tun=Y     |            |
   |         | ---------------->| DNAT flows |
   |         |                  |            |
   |         | in_port=br-ex    | Dest port  |
   |         | ---------------->| lookup     |
   |         |                  |            |
   +---------+                  +------------+


Option 2
~~~~~~~~

Route all VLAN=0 and external port traffic to a new table
INGRESS_FLAT_NETWORK_CLASSIFICATIOB_TABLE, with DNAT rules and low priority
flow to send the rest of the traffic to INGRESS_DESTINATION_PORT_LOOKUP_TABLE(7)


   +---------+                            +------------+
   | Table 0 |                            |  Table 7   |
   |         | vlan=X/tun=Y               |            |
   |         | -------------------------->| DNAT flows |
   |         |                            |            |
   |         | in_port=br-ex/vlan=0       | Dest port  |
   |         | ----------+        +------>| lookup     |
   |         |           |        | else  |            |
   +---------+           v        |       +------------+
                       +-------------+
                       |  New table  |
                       |             |
                       | DNAT flows  |
                       |             |
                       | Else:       |
                       |  goto 7     |
                       |             |
                       +-------------+

References
==========


