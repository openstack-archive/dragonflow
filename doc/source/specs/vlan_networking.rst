..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===============
Vlan Networking
===============

https://blueprints.launchpad.net/dragonflow/+spec/vlan-network

This blueprint describes how to implement vlan L2 networking in Dragonflow.

Problem Description
===================
Currently, Dragonflow only supports overlay network.
When admin creates network,no network type can be chosen.
The network type is always set to overlay network (VxLan, GRE...).
Whereas, there're some demands for other network types, such as vlan,
flat, etc. If vm belongs to vlan network, a vlan header(802.1.Q) will be
encapsulated within the packet, and forwarded to the physical network through
the host physical nic.

This spec just discusses how to support vlan L2 networking.


Proposed Change
===============
First, Dragonflow plugin does not support to create vlan network.
In future, ML2 Mechanism Driver will replace Dragonflow Plugin to support
vlan network.

Second, Dragonflow Controller needs to handle port updated events
as overlay scenario does, and install flows to openvswitch.

Third, openflow tables and items for vlan network needs to
coordinate with existing flow items, so that all work fine together.

What does dragonflow need to do for vlan  L2 networks
is similar to overlay networking.
The difference between them is what flow items should be installed.

When controller receives port updated messages from dragonflow plugin,
it will handle them just as what it does for vxlan, and install flows.

When controller receives port online events from ovsdb monitor,
it will query port and network information from db store..
If  this is the first port belongs to a tenant in this host,
local controller will subscribe northbound events.

When controller receives port deleted messages,
it will delete corresponding flow items.

Packets from vms or outside such as tunnel and physical nics
will be handled differently.
Here we call from vms is outbound direction, from outside is inbound direction.
These two directions will be discussed separately.

Two bridges per host
--------------------
VMs are connected to br-int,
overlay tunnels connected to br-int, physical nic connected to br-1,
Vlan Packets are transmitted to/from br-1.

Port updated
------------
When controller receives port updated messages, it will install flows.
With this, outbound and inbound will be discussed as follows.

Outbound
^^^^^^^^
Packets are divided into three types:
arp,dhcp, broadcast/multicast.
These three types will be handled differently by the dragonflow controller.

Outbound-Arp
""""""""""""

local port
~~~~~~~~~~
When controller receives local port updated message,
it will  install flows on ovs to act as arp proxy.
This can eliminate arp broadcast for known ports.
With unknown outside servers, this will be treated as common broadcast.

For arp responder, vlan is same as vxlan.
Openflow items like this:
Table=ARP, Match: Arp Request, Actions: Arp Responders.

remote port
~~~~~~~~~~~
When controller receives remote port updated message,
it will install flows as what local scenario does.
If destination is unknown, arp request will be handled as common broadcast,
which will be discussed as follows.


Outbound-DHCP
"""""""""""""
If 'dhcp enable' option is chosen with vlan network,
controller acts as dhcp server to respond for dhcp request.
If 'dhcp enable' option is off, dhcp broadcast is treated as common broadcast.
Actually it's same as what is done for vxlan network.


Outbound-Common Broadcast/Multicast
"""""""""""""""""""""""""""""""""""
Broadcast excepts to arp and dhcp, it's similar to multicast processing.
We just take broadcast for example.
When broadcast happens, thus packet should be forwarded to local ports,
remote ports and unknown outside servers belong to the same vlan.

For remote and unknown outside ports, controller just needs to push vlan header
and forward packets to br-1(external).
Then br-1 will send packets to the physical nic
according to the flows on br-1 "table=0, priority=0, Actions=Normal".

Outside forwarding behaviors depends on physical networks,
which will be not discussed here.

local port
~~~~~~~~~~
When controller receives local port updated messages,
if this port is the first port of the network on the host,
controller will install broadcast flows on ovs like this:
1.Table=L2_Lookup,
Match: metadata=network_id, dl_dst=01:00:00:00:00:00/01:00:00:00:00:00,
Actions:  resubmit(,EGRESSTABLE), load_reg7=port_unique_key,resubmit(,EGRESSTABLE)

2.Table=Egress_Table,
Match: metadata=network_id,
Actions:mod_vlan=vlan_id,output:path_br_1

If this port is not the first one, controller only update the first flow above.

remote port
~~~~~~~~~~~
When controller receives remote port updated message, it will not update
broadcast flows. Because with broadcast, ovs just needs to forward it to br-1.
This has been done when local port updated.like this.
1.Table=L2_Lookup,
Match: metadata=network_id, dl_dst=01:00:00:00:00:00/01:00:00:00:00:00,
Actions:  resubmit(,EGRESSTABLE), load_reg7=port_unique_key,resubmit(,EGRESSTABLE)

The first action 'resubmit(,EGRESSTABLE)' has included remote broadcast scenario.


Outbound-Unicast
""""""""""""""""
For unicast, controller treats them differently according to destination port.

local port
~~~~~~~~~~
When controller receives local ports updated message,
it will install flows for unicast forwarding.

If it is the first port of the network locally,
controller will install flow for remote and unknown ports.
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
With inbound, a flow item will be installed to table 0, which will strip vlan
and set metadata for next table. Flow item like this:
Table=0,
Match:dl_vlan=network_vlan_id,
Actions:metadata=network_id, strip_vlan, goto "Destination Port Classification".

For simplicity, I will omit some flow tables that are not so directly related
with vlan networking.

Inbound-Arp
"""""""""""
Inbound arp broadcast will be handled as common broadcast,
which will be discussed as follows .

Inbound-DHCP
""""""""""""
DHCP Request will be handled by controller that acts as DHCP server,
so if inbound dhcp packets are received,, nothing needs to be done.

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


Port delete
-----------
When controller receive port deleted messages, it will delete corresponding
flow items as above.
What's more, there's some special scenario if the deleted port is the last
port on this host which belongs to the network.
On the last local port deleted of a network, network flow items  for remote and
unknown ports should be also deleted..
