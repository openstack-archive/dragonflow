..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===============
Vlan Networking
===============

https://blueprints.launchpad.net/dragonflow/+spec/vlan-network

This blueprint describes how to implement VLAN L2 networking in Dragonflow.

Problem Description
===================
Currently, Dragonflow only supports overlay network.
When admin creates network, no network type can be chosen.
The network type is always set to overlay network (VxLAN, GRE...).
Whereas, there're some demands for other network types, such as VLAN,
flat, etc. If a VM belongs to a VLAN network, a VLAN header(802.1.Q) will be
encapsulated within the packet, and forwarded to the physical network through
the host physical NIC.

This spec just discusses how to support VLAN L2 networking.


Proposed Change
===============
First, Dragonflow plugin does not support to create VLAN network.
In the future, ML2 Mechanism Driver will replace Dragonflow Plugin to support
VLAN network.

Second, Dragonflow Controller needs to handle port updated events
as overlay scenario does, and install flows to OpenvSwitch.

Third, OpenFlow tables and items for VLAN network needs to
coordinate with existing flow items, so that all work fine together.

What dragonflow need to do for VLAN L2 networks is similar to overlay
networking.
The difference between them is what flow items should be installed.

When controller receives port updated messages from Dragonflow plugin,
it will handle them just as what it does for VxLAN, and install flows.

When controller receives port online events from OVSDB monitor,
it will query port and network information from db store..
If this is the first port belongs to a tenant in this host,
local controller will subscribe to northbound events.

When controller receives port deleted messages,
it will delete corresponding flow items.

Packets from VMs or outside such as tunnels and physical NICs
will be handled differently.
Here we call from VMs is outbound direction, from outside is inbound direction.
These two directions will be discussed separately.

Two Bridges Per Host
--------------------
VMs are connected to br-int,
overlay tunnels connected to br-int, physical NIC connected to br-1,
VLAN packets are transmitted to/from br-1.

Port Updated
------------
When controller receives port updated messages, it will install flows.
With this, outbound and inbound will be discussed as follows.

Outbound
^^^^^^^^
Packets are divided into three types:
ARP, DHCP, broadcast/multicast.
These three types will be handled differently by the Dragonflow controller.

Outbound-ARP
""""""""""""

Local Port
~~~~~~~~~~
When controller receives local port updated message,
it will install flows on OVS to act as ARP proxy.
This can eliminate ARP broadcast for known ports.
With unknown outside servers, this will be treated as common broadcast.

For ARP responder, VLAN is same as VxLAN.
OpenFlow items like this:
Table=ARP, Match: ARP Request, Actions: ARP Responders.

Remote Port
~~~~~~~~~~~
When controller receives remote port updated message,
it will install flows as what local scenario does.
If destination is unknown, ARP request will be handled as common broadcast,
which will be discussed as follows.


Outbound-DHCP
"""""""""""""
If 'dhcp enable' option is chosen with VLAN network,
controller acts as a DHCP server to respond for DHCP request.
If 'dhcp enable' option is off, DHCP broadcast is treated as common broadcast.
Actually it's same as what is done for VxLAN network.


Outbound-Common Broadcast/Multicast
"""""""""""""""""""""""""""""""""""
Broadcast excepts ARP and DHCP, it's similar to multicast processing.
We just take broadcast for example.
Broadcast packets should be forwarded to local ports,
remote ports and unknown outside servers belong to the same VLAN.

For remote and unknown outside ports, controller just needs to push VLAN header
and forward packets to br-1(external).
Then br-1 will send packets to the physical NIC
according to the flows on br-1 "table=0, priority=0, Actions=Normal".

Outside forwarding behaviors depends on physical networks,
which will be not discussed here.

Local Port
~~~~~~~~~~
When controller receives local port updated messages,
if this port is the first port of the network on the host,
controller will install broadcast flows on OVS like this:
1.Table=L2_Lookup,
Match: metadata=network_id, dl_dst=01:00:00:00:00:00/01:00:00:00:00:00,
Actions:  resubmit(,EGRESSTABLE), load_reg7=port_unique_key,resubmit(,EGRESSTABLE)

2.Table=Egress_Table,
Match: metadata=network_id,
Actions:mod_vlan=vlan_id,output:path_br_1

If this port is not the first one, controller only updates the first flow above.

Remote Port
~~~~~~~~~~~
When controller receives remote port updated message, it will not update
broadcast flows. Because with broadcast, OVS just needs to forward it to br-1.
This has been done when local port updated.like this.
1.Table=L2_Lookup,
Match: metadata=network_id, dl_dst=01:00:00:00:00:00/01:00:00:00:00:00,
Actions:  resubmit(,EGRESSTABLE), load_reg7=port_unique_key,resubmit(,EGRESSTABLE)

The first action 'resubmit(,EGRESSTABLE)' has included remote broadcast scenario.


Outbound-Unicast
""""""""""""""""
For unicast, controller treats them differently according to destination port.

Local Port
~~~~~~~~~~
When controller receives local ports updated message,
it will install flows for unicast forwarding.

If it is the first port of the network locally,
controller will install flows for remote and unknown ports.
1.Table=L2_Lookup, Match: reg7=port_unique_key, Actions: output:ofport
2.Table=L2_Lookup, Match: metadata=network_id,
dl_dst=00:00:00:00:00:00/01:00:00:00:00:00,  Actions: goto "Egress_Table"
3.Table=Egress_Table,Match: metadata=network_id,mod_vlan=network_vlan_id,
output:path_br_1

If this is not the first one, only the first flow above will be installed.

Remote Port
~~~~~~~~~~~
When controller receives remote ports updated messages,
it will not install flow for unicast.
Because this has been done when first port updated.


Inbound
^^^^^^^
With inbound, a flow item will be installed to table 0, which will strip VLAN
tag and set metadata for next table. Flow item like this:
Table=0,
Match:dl_vlan=network_vlan_id,
Actions:metadata=network_id, strip_vlan, goto "Destination Port Classification".

For simplicity, I will omit some flow tables that are not so directly related
with VLAN networking.

Inbound-ARP
"""""""""""
Inbound ARP broadcast will be handled as common broadcast,
which will be discussed as follows .

Inbound-DHCP
""""""""""""
DHCP Request will be handled by controller that acts as DHCP server,
so if inbound DHCP packets are received, nothing needs to be done.

Inbound-Unicast
"""""""""""""""
When controller receives local port updated messages,
it will install flow items like this.

1. Table=Destination_Port_Classification,
Match:metadata=network_id, dl_dst=port_mac,
Actions= load_reg7=port_unique_key, goto "Destination_Port_Dispatch"
2. Table=Destination_Port_Dispatch,
Match: reg7=port_key, Actions: output:ofport


Inbound-Broadcast/Multicast
"""""""""""""""""""""""""""
When controller receives local port updated message,
it will install or update flow like this.

1. Table=Destination_Port_Classification,
Match:metadata=network_id, dl_dst==01:00:00:00:00:00/01:00:00:00:00:00,
Actions= load_reg7=port_unique_key_1, goto "Destination_Port_Dispatch",
load_reg7=port_unique_key_2, goto "Destination_Port_Dispatch"
2. Table=Destination_Port_Dispatch,
Match: reg7=port_unique_key, Actions: output:ofport


Port Delete
-----------
When controller receive port deleted messages, it will delete corresponding
flow items as above.
What's more, there's some special scenario if the deleted port is the last
port on this host which belongs to the network.
On the last local port deleted of a network, network flow items for remote and
unknown ports should be also deleted..
