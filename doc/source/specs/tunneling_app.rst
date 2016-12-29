 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==================
Tunneling App
==================

 https://blueprints.launchpad.net/dragonflow/+spec/Tunneling-app

The tunneling  app is taking care for the processing of segmented overlay
networks.

Tunneling Application is responsible for creating and updating overlay
connectivity with other compute hosts a.k.a chasis.

Problem Description
===================
Tunneling is currently handled both by the df_local_controller and by the
L2 application for both ingress and egress packets propagation.
The tunneling related flows are set when either local or remote port is updated.

Upon VM port creation, its properties such as it's overlay network membership,
ports database id is used to match flows to/from it. 

* metadata <- Unique network ID

::
   (neutron) net-list
   +--------------------------------------+---------------+----------------------------------------------------+
   | id                                   | name          | subnets                                            |
   +--------------------------------------+---------------+----------------------------------------------------+
   | 1ef7411e-1e9c-41b7-92d6-b38a9f8619ca | public        | 3a19fd0c-e412-4e6e-8991-9c125ed7705b 172.24.4.0/24 |
   | 5c49ac27-a2e1-4922-9030-8ce44cf91a2d | admin-private | bde742b9-10bc-4ac0-9d75-4665039643c6 10.10.0.0/24  |
   | bc5eb406-f338-401a-a8db-18bb9536ad54 | private       | 9450856c-bd96-41fd-ae96-9f922cda5f0a 10.0.0.0/24   |
   +--------------------------------------+---------------+----------------------------------------------------+

   ...

   net-show 5c49ac27-a2e1-4922-9030-8ce44cf91a2d (admin-private)
   | provider:segmentation_id  | 19
   ...
   net-show bc5eb406-f338-401a-a8db-18bb9536ad54 (private)
   | provider:segmentation_id  | 73

Ingress Proccessing
-------------------

The classification flow should match against segmentation id and the set reg 7
as unique port key to identify this port for destination matching.
An example classification flow, for two VMS, one is part of "admin-private"
network, with segmentation id 0x13 and the second which is part of "private"
network with segmentation id 0x49, the classification flows for these tunnels
are: 

::
   dump-flows  br-int table=0

   table=0, priority=100,tun_id=0x13 actions=load:0x3->OXM_OF_METADATA[],resubmit(,7)
   table=0, priority=100,tun_id=0x49 actions=load:0x1->OXM_OF_METADATA[],resubmit(,7)

In the ingress port lookup table, 7 a match is done according to unique 
network id and vm's port mac, where vm's port key is set into reg7, and sent to
table 72 is the ingress conn-track table which passes the packet to ingress
dispatch table  

* reg7 <- Unique port key

::
   dump-flows br-int table=7

   table=7, priority=200,metadata=0x3,dl_dst=fa:16:3e:4d:a9:26 actions=load:0x2->NXM_NX_REG7[],resubmit(,72)
   table=7, priority=200,metadata=0x1,dl_dst=fa:16:3e:bc:5b:08 actions=load:0x6->NXM_NX_REG7[],resubmit(,72)

Eventually the processing reaches table 78, the ingress dispatch table where 
the packet which is matched against port's key, and forwarded to the local vm
port 

::
   table=78,  priority=100,reg7=0x6 actions=output:7

Egress Proccessing
------------------
A classification flow related to egress dispatching  is set to be initially
filtered by the security table the flow sets port key and network id to reg6 
and metadata ovs registers

::
    table=0, priority=100,in_port=8 actions=load:0xa->NXM_NX_REG6[],load:0x1->OXM_OF_METADATA[],resubmit(,1)

In the security table, 1 the flow makes sure that the packet has originated
from VM's assigned address and prevent network address spoofing and passed
to conn. track table.

::
    table=1, priority=200,in_port=8,dl_src=fa:16:3e:95:bf:e9,nw_src=10.0.0.5 actions=resubmit(,3)

The conn. track table is used to create connection tracing entry in Linux
Kernel, and passes the packet to service classification table.
The service classification table filters out service oriented packets and pass
the packet to the L2 lookup table

::
    table=3, priority=1 actions=resubmit(,9)

The service classification table filters out service oriented packets and pass
the packet to the L2 lookup table

Egress processing - L2 lookup
-----------------------------
For locally originated traffic, the destination mac and network membership are
translated to port key which is push to reg7, and passed to egress table 64,
it will go through the conn. track table and eventfully dispatched locally
same as ingress traffic

::
   table=64, priority=100,reg7=0xa actions=resubmit(,72)

For BUM replication on all known ports in a certain network traffic the
following flow is set

::
   table=17, priority=100,metadata=0x1,dl_dst=01:00:00:00:00:00/01:00:00:00:00:00 actions=load:0xa->NXM_NX_REG7[],resubmit(,64),load:0x2->NXM_NX_REG7[],resubmit(,64),load:0->NXM_NX_REG7[],resubmit(,64)


Add remote port
---------------
A flow in the  L2 lookup is planted to translate ne VM mac and network to it's
port key in Reg7 and pass to egress table 64

::
    table=17,priority=100,metadata=0x1,dl_dst=fa:16:3e:2d:cc:cd actions=load:0xc->NXM_NX_REG7[],resubmit(,64)


To forward the traffic via the tunnel port this flow is matched against the
remote port key set in reg7. 

::
    table=64,reg7=0xc actions=load:0x49->NXM_NX_TUN_ID[],output:8

Proposed Change
===============
A new tunneling application that will deal with tunneling related flows

*ingress processing
 it will set the tunnel matching classification flow in table 0, and local
 port lookup in l2 lookup table 7 

*egress processing
it will set the the flows dispatch to tunnel port upong remote port match or
for local dispatch,and  bum traffic flows 
