 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

======================
Provider networks App
======================

https://blueprints.launchpad.net/dragonflow/+spec/provider-networks-app

The Provider networks app is handling the connectivity with the physical
provider network underlay and takes care of the arriving/leaving packets
between providers underlay and local vm's.

See also neutron provider networks documentation:
https://docs.openstack.org/liberty/networking-guide/intro-os-networking-overview.html#Provider%20networks

Problem Description
===================
Provider networks is currently handled both by the L2 application for both
ingress and egress packets propagation.
The forwarding flows to or from physical provider's networks are set when
a local or remote port is created/updated.

If the VM port is part of a vlan network, a flow is created to translate
vlan-id to network metadata, and set it's port key in reg6/reg7

Set fields are:

* metadata <- network's Unique ID
* reg6 <- unique port key, for egress remote forwarding processing
* reg7 <- unique port key, for ingress local l2 lookup processing

Ingress Proccessing
-------------------
A classification flow should match against vlan membership in case of vlan
network. or use the untagged vlan id 0 to match flat networks traffic.

Egress Proccessing
------------------
For locally originated traffic, the destination mac and network membership are
translated to port key which is push to reg7, and passed to EGRESS_TABLE.

In the EGRESS_EXTERNAL_TABLE according to network membership, a vlan tag is
added.
The remote port key is translated to mac address to be forwarded via the
EGRESS_EXTERNAL_TABLE table to the local patch port related to underlay
provider's network.

Proposed Change
===============
A new provider network application that will deal with vlan and flat related
flows.

On setup it will create the patch ports according to bridge-network mapping
configuration parameters from the local integration bridge to the bridges 
connected with the provider networks.

Ingress processing
------------------
Will set the vlan/flat matching classification flow in table 0,  and forward
it to l2 lookup table. The lookup mechanism should treat all port equally and
filter according to port key.

egress processing
-----------------
Will set the flows to forward traffic going from the chassis to the
underlay via the patch port connected to the underlay network.
Match locally dispatched traffic and set egress bum traffic flows.

L2 application will deal with all local network flows that are neither related
to how the packets arrived at the integration switch, nor how they leave.
It will be up to other application to set the flows that translate the local
destination port to reg7, and remote reg7 for pushing the packet down stream.

