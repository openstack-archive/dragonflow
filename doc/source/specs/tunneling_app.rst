 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=============
Tunneling App
=============

 https://blueprints.launchpad.net/dragonflow/+spec/Tunneling-app

The tunneling app is taking care for the processing of segmented overlay
networks.

Tunneling Application is responsible for creating and updating overlay
connectivity with other compute hosts a.k.a chassis.

Problem Description
===================
Tunneling is currently handled both by the df_local_controller and by the
L2 application for both ingress and egress packets propagation.
The tunneling related flows are set when either local or remote port is updated.

Upon VM port creation, its properties such as its overlay network membership,
ports database id is used to match flows to/from it. A tunnel port is created
upon df_local_controller start up. As the tunnel port is shared among many
networks. A flow is set to convert segmentation id to network id set in the
metadata field of the OVS.

Set fields are:
* metadata <- network's Unique ID

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

Ingress Processing
------------------

The classification flow should match against the tunnel in_port, a port of a
specific segmentation id and tunnel's virtual network key, according
to which metadata will be set as network_id to identify incoming traffic being part
of the network identified by the segmentation id.

An example classification flow, for two VMS, one is part of "admin-private"
network, with segmentation id 0x13 and the second which is part of "private"
network with segmentation id 0x49, the classification flows for these tunnels
are:

::

   dump-flows  br-int table=0

   table=0, priority=100,in_port=4,tun_id=0x13 actions=load:0x3->OXM_OF_METADATA[],resubmit(,100)
   table=0, priority=100,in_port=4,tun_id=0x49 actions=load:0x1->OXM_OF_METADATA[],resubmit(,100)

Currently in the ingress port lookup table (100), a match is done according to unique
network id and vm's port mac, where vm's port key is set into reg7, and sent to
table (105), the ingress conn-track table which passes the packet to ingress
dispatch table

Set fields are:
* reg7 <- Unique port key

::

   dump-flows br-int table=100

   table=100, priority=200,metadata=0x3,dl_dst=fa:16:3e:4d:a9:26 actions=load:0x2->NXM_NX_REG7[],resubmit(,105)
   table=100, priority=200,metadata=0x1,dl_dst=fa:16:3e:bc:5b:08 actions=load:0x6->NXM_NX_REG7[],resubmit(,105)

Eventually the processing reaches table (115), the ingress dispatch table where
the packet is matched against vm's port's key, and forwarded to the local vm port.

::

   table=115, priority=100,reg7=0x6 actions=output:7

Egress Processing
-----------------
A classification flow related to egress dispatching is set to be initially
filtered by the security table, the flow sets port key and network id to reg6,
and metadata ovs registers, respectively.

::

    table=0, priority=100,in_port=8 actions=load:0xa->NXM_NX_REG6[],load:0x1->OXM_OF_METADATA[],resubmit(,5)

In the security table (5), the flow makes sure that the packet has originated
from VM's assigned address and prevent network address spoofing, making the packet goto
the 'connection track' table (10).

::

    table=5, priority=200,in_port=8,dl_src=fa:16:3e:95:bf:e9,nw_src=10.0.0.5 actions=resubmit(,10)

The 'connection track' table is used to create a connection track entry in Linux
Kernel, and pass the packet to the service classification table.
The service classification table filters out service oriented packets and pass
the packet to the L2 lookup table, same as any other network type.

::

    table=10, priority=1 actions=resubmit(,20)

Egress processing - L2 lookup
-----------------------------
For locally originated traffic, the destination mac and network membership are
translated to port key which is pushed to reg7, and passed to egress table 64,
it will go through the connection track table and eventfully dispatched locally
same as ingress traffic

::

   table=75, priority=100,reg7=0xa actions=resubmit(,105)

For BUM replication on all known ports in a certain network traffic the
following flow is set

::

   table=55, priority=100,metadata=0x1,dl_dst=01:00:00:00:00:00/01:00:00:00:00:00 actions=load:0xa->NXM_NX_REG7[],resubmit(,75),load:0x2->NXM_NX_REG7[],resubmit(,75),load:0->NXM_NX_REG7[],resubmit(,75)


Add remote port
---------------
A flow in the  L2 lookup (55) is planted to translate VM mac and network membership
to it's port key in Reg7 and pass to egress table 75

::

    table=55,priority=100,metadata=0x1,dl_dst=fa:16:3e:2d:cc:cd actions=load:0xc->NXM_NX_REG7[],resubmit(,75)


To forward the traffic via the tunnel port this flow is matched against the
remote port key set in reg7 and is output through the tunnel port.
192.168.20.22 is the IP address of the destination compute host.

::

    table=75,reg7=0xc actions=load:0x49->NXM_NX_TUN_ID[],load:0xC0A81416->NXM_NX_TUN_IPV4_DST[],output:8

Proposed Change
===============
L2 application will deal with all local network flows that are neither related
to how the packets arrived at the integration switch, nor how they leave.
It will be up to other application to set the flows that translate the local
destination port to reg7, and remote reg7 to pushing the packet down stream.
A new tunneling application that will deal with tunneling related flows

Ingress processing
------------------
it will set the tunnel matching classification flow in table 0,  and forward
it to l2 port lookup table (100). The lookup
mechanism should treat all port equally and filter according to port key.

::


   table=0, priority=100,in_port=4,tun_id=0x13 actions=load:0x3->OXM_OF_METADATA[],resubmit(,100)
   table=0, priority=100,in_port=4,tun_id=0x49 actions=load:0x1->OXM_OF_METADATA[],resubmit(,100)


Egress processing
-----------------
it will set the flows to dispatch traffic going from the chassis to the
remote port via the tunnel port and match locally dispatched traffic and set
egress bum traffic flows.

::

   table=75, priority=100,reg7=0xa actions=resubmit(,105)
   table=100, priority=100,metadata=0x1,dl_dst=01:00:00:00:00:00/01:00:00:00:00:00 actions=load:0xa->NXM_NX_REG7[],resubmit(,75),load:0x2->NXM_NX_REG7[],resubmit(,75),load:0->NXM_NX_REG7[],resubmit(,75)

Impact on other DF applications
-------------------------------
The changes in the L2 application will affect the Provider Networks App. DNAT App, SNAT App et al.

According to the propsed design, L2 application deals with local chassis flows, while
the 'tunneling app', 'provider networks app', 'DNAT app' and 'SNAT app', should deal
with setting the flows for incoming/outgoing packets from/to external nodes.

Work Items
----------

1. Create a new tunneling application.
2. Add tunneling app to "Plugin.sh".
3. Remove the tunneling code from the l2 application.
4. Add unit tests, to reflect code changes.

