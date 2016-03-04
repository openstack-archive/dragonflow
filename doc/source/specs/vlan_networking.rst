
..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode


======================
Vlan Networking
======================
This blueprint describes how to implement vlan L2 networking in Dragonflow.


Problem Description
===================
Currently, Dragonflow only supports overlay network. 
When admin creates network,no network type can be chosed.
Whereas, there¡¯re some demands for other network type, such as vlan, flat, etc.
This spec just discusses how to support vlan L2 networking.


Proposed Change
===================
First, Dragonflow plugin does not support to create vlan network. 
In future, ML2 Plugin will replace Dragonflow Plugin to support vlan network.

Second, Dragonflow Controller needs to handle port updated events 
as overlay scenario does, and install flows to openvsiwtch.

Third, openflow tables and items for vlan network needs to 
coordinate with existing flow items, so that all work fine together.

What does dragonflow need to do for vlan  L2 networking
is similar to overlay networking. 
The difference between them is what flow items should be installed.

When controller receive port updated messages from dragonflow plugin,
it will handle them just as what vxlan does, and install flows.

When controller receive port online events from ovsdb monitor,
it will query port and network inforamton from memory db.
If  this is the first port belongs to a tenant, 
local controller will subscribe northbound events.

When controller receive port deleted messages,
it will delete correspongding flow items.

Packets from vms or outside such as tunnel and physical nics 
will be handled differently.
Here we call from vms is outbound direction, from outside is inbound direction.
Two directions will be discussed separately.

If destination ports reside in the same hosts with local controller, 
these are called local ports. Otherwise, those are called remote ports.

Currently there¡¯re several bridge topologies with different vendors. 
Here we just talk about two mainly topologies.

One bridge per host
--------------------
One bridge per host, physical nic is connected to br-int,
which is usally called uplink port. 
Vlan packets for remote or broadcast will be sent to uplink.
+---------------------------------+
|      VM1    VM2                 |
|       +      +                  |
|   +-+---------------------+     |
|   | | |local |            |     |
|   | | +------+   br+int   |     |
|   +-----------------------+     |
|     |               |uplink     |
|     |               |           |
+---------------------nic---------+
      |
      |
      |Remote/Broadcast
      |
      v

Three bridges per host
----------------------
VMs are connected to br-int, 
overlay tunnels connected to br-tun, physical nic connected to br¡ª1.  
Vlan Packets are transmited to/from br-1. 
With this topology, we will add a flow table called 'ingress' to 
handle inbound packets.
 
|----------------------------------
|      VM1    VM2                 |
|       |      |                  |
|   +-+---------------------+     |
|   | | |local |            |     |
|   | | +------+   br-int   |     |
|   +-----------------+-----+     |
|     |  patch        |           |
|   +----------+  +---+--------+  |
|   | |br-1    |  |   br-tun   |  |
|   | |        |  |            |  |
|   +----------+  +------------+  |
+-----nic-------------------------+
      |
      |
      |Remote/Broadcast
      v
This spec, we will discuss Vlan L2 networking with the second one.
With first one, it's similar to the second.


Port updated  
********************************************************************
When controller receive port updated messages, it will install flows.
With this, outbound and inbound will be discussed as follows.

Outbound
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Packets are divided into four types: 
arp,dhcp, broadcast/multicast. 
For each type, drangonflow controller will handle differently.

Outbond-Arp
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

local port
----------
When controller receives local port updated message, 
it will  install flows on ovs to act as arp proxy. 
Thus can eliminate arp brocast for known ports.
With unkown outside servers, thus will be tread as common broadcast.

Openflow items ike this:
Table=ARP, Match: Arp Request, Actions: Arp Responders.

remote port
--------------
When controller receives remote port updated message, 
it will install flows as what local scenario does.
If detination is unknown, arp request will be handled as common broadcast,
which will be discussed as follows.
 
 
Outbound-DHCP 
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
If 'dhcp enable' option is chosed with vlan network, 
controller acts as dhcp server to reponse for dhcp request.


Outbound-Common Broadcast/Multicast
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Broadcast excepts  arp and dhcp, it¡¯s similar to multicast processing. 
We just take broadcast for example. 
When broadcast happens, thus packet should be forwarded to local ports, 
remote port and unkown outside servers belong to the same vlan.  

For remote and unkown outside ports, controller just needs to push vlan header 
and forward packets to br-1(external). 
Then br-1 will send packets to the physical nic  
according to the flows on br-1 "table=0, priority=0, Actions=Normal".

Outside forwarding behaviors depends on physical networks,
which will not discussed here.

local port
-------------
When controller receives local port updated messages, 
if this port is the first port of the network, 
controller will install broadcast flows on ovs like this:
1.Table=L2_Lookup, 
  Match: metadata=network_id, dl_dst=01:00:00:00:00:00/01:00:00:00:00:00,
  Actions: load_reg7=tunnel_id,_1,resubmit(,EGRESSTABLE,)
           , resubmit(,EGRESSTABLE)
2.Table=Egress_Table,
  Match: metadata=network_id, 
  Actions:mod_vlan=10,output:path_br_1

If this port is not the first one, controller only update the first flow above.

remote port
-----------
When controller receives remote port updated message,
it will not update flows. Because with broadcast, 
ovs needs to forward it to patch. Thus has been done when local port updated.


Outbound-Unicast
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For unicast, controller treats them differently according to destination port.

local port 
-----------
When controller receives local ports updated message,
it will install flows for unicast forwarding.

If it is the first port of the network locally,
controller will install flow for remote and unkown servers.
1.Table=L2_Lookup, Match: reg7=port_unique_key, Actions: output:ofport
2.Table=L2_Lookup, Match: metadata=network_id, 
dl_dst=00:00:00:00:00:00/01:00:00:00:00:00,  Actions: goto "Egress_Table"
3.Table=Egress_Table,Match: metadata=network_id,mod_vlan=10,output:path_br_1

If this is not the first one, only the first flow above will be installed.

Remote
----------
When controller receives remote ports updated messages, 
it will not install flow for unicast.
Because this has been done when first port updated.


Inbound
~~~~~~~~~~~~~~~~~~~~~~~~

Inbound-Arp
~~~~~~~~~~~~~~~~~~~~~~~~
Inbound arp broadcast will be handled as common broadcast, 
which will be discussed as follows .

Inbound-DHCP
~~~~~~~~~~~~~~~~~~~~~~~
DHCP Request will be handled by controller that acts as dhcp server, 
so if inbound dhcp happends, nothing needs to do.

Inbound-Unicast
~~~~~~~~~~~~~~~~~~~~~~~
When controller receives local port updated messages, 
it will install flow items like this.
Table=Ingress, Match dl_vlan=10,dl_dst=port_mac, 
Actions: strip_vlan, output: of_port

Broadcast/Multicast
~~~~~~~~~~~~~~~~~~~~~~~~
When controller receives remote port updated message£¬ 
it will install or update flow like this£º
Table=Ingress, Match dl_vlan=10,dl_dst=01:00:00:00:00:00/01:00:00:00:00:00 
Actions:strip_vlan,output:port1, port2, port3


Ported delete
==========
When controller receive port deleted messages, it will delete correspongding
flow items as above.