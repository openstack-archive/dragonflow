 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

======================
Provider networks App
======================

 https://blueprints.launchpad.net/dragonflow/+spec/Provider-networks-app

The Provider networks app is handling the connectivity with the physical 
provider network underlay and takes care of the arriving/leaving packets 
between providers underlay and local vm's.

Problem Description
===================
Upon VM port creation, its properties such as it's network membership
and port's database id are used to match flows to/from it.

If the VM is part of a virtual lan network. A flow is created to translate 
vlan id to network metadata, and set it's port key in reg7 

Set fields are:
* metadata <- network's Unique ID
* reg7 <- unique port key

Ingress Proccessing
-------------------
A classification flow should match against vlan membership in case of vlan
network. or use the untagged vlan id 0 to match flat networks traffic.

Egress Proccessing
------------------
For locally originated traffic, the destination mac and network membership are
translated to port key which is push to reg7, and passed to egress table 64,

In the Egress table according to network membership, a vlan tag is added.
and remote port key is translated to mac address to be forwarded via the 
Egress external table to the patch port connected to the providers underlay
networks.

Proposed Change
===============
A new provider network application that will deal with vlan and flat related
flows

*ingress processing
it will set the vlan/flat matching classification flow in table 0,  and forward 
it to l2 lookup table. The looup mechnism should treat all port equily and
filter according to port key.

*egress processing
it will set the the flows to dispatch traffic going from the chassis to the 
underlay via the patch port connected to the underlay.
match locally dispatched traffic and set egress bum traffic flows.

L2 application will deal with all local network flows that are niether related
to how the packets arrived at the integration switch, nor how they leave.
It will be up to other application to set the flows that translte the local
destintion port to reg7, and remote reg7 to pushing the packet down stream.

The related application are Provider Network App. Dnat App, Snat App etc..
