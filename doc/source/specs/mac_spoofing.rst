..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==============================
Port Security and MAC Spoofing
==============================

https://blueprints.launchpad.net/dragonflow/+spec/mac-spoofing-protection

This blueprint describes how to implement MAC spoofing protection for
Dragonflow.

Problem Description
===================
In current Neutron implementation MAC spoofing protection rules are added
implicitly to each VM port, these rules are not part of the security groups
feature.

Without this protection a VM in a network can spoof and answer
to ARP requests that don't actually belong to it, or fake response for
other VM.

Proposed Change
===============
A new table is added in Dragonflow pipeline for mac spoofing protection.

This table will have MAC-IP validation rules which blocks any traffic
that has different MAC-IP src address than the MAC-IP address configured for the VM.
This table can also be used for egress security validations (make sure
to dispatch traffic to a certain VM only if it has the correct configured MAC and IP)

It will also have rules allowing DST broadcast/multicast MAC traffic
to pass.

Additional drop rules:

1. Packets with SRC MAC broadcast/multicast bit set.
   (This option might be needed in some environments, we can leave this as a configurable
   option in case it is -
   http://www.cisco.com/c/en/us/support/docs/switches/catalyst-6500-series-switches/107995-config-catalyst-00.html#mm)

2. VLAN tagged frames where the TCI "Drop eligible indicator" (TEI) bit is set (congestion)

Following are examples for the flows configured in that table::

     match:vlan_tci=0x1000/0x1000 actions=drop
     match:dl_src=01:00:00:00:00:00/01:00:00:00:00:00 actions=drop

     match:metadata=0x2,dl_src=fa:16:3e:d6:87:a7 actions=resubmit(,<next_table>)


This table also blocks any ARP responses with IPs that don't belong
to this VM port.
(Same for ND responses for IPv6)

::

    +------+        +-------------------------------------------------------------------------------------+
    |      |        |                                                                                     |
    |  VM  |        |   OVS Dragonflow Pipeline                                                           |
    |      |        |                                                                                     |
    +---+--+        |   +----------------+       +-------------+        +-----------+     +------------+  |
        |           |   |                |       |             |        |           |     |            |  |
        |           |   |                |       |  MAC        |        | Security  |     |  Dispatch  |  |
        |           |   | Port           |       |  Spoofing   |        | Groups    |     |  To        |  |
        +-------------->+ Classification +-----> |  Protection +------->+ Ingress   +---->+  Local     |  |
           |        |   | (Table 0)      |       |  Table      |        |           |     |  Ports     |  |
                    |   |                |       |             |        |           |     |            |  |
                    |   |                |       |             |        |           |     |            |  |
                    |   +----------------+       +-------------+        +-----------+     +------------+  |
                    |                                                                                     |
                    |                                                                                     |
                    +-------------------------------------------------------------------------------------+


Allowed Address Pairs
---------------------
In Neutron there is a feature called allowed address pairs [1], this allow you
to define <mac, ip> pairs that are allowed for a specific port regardless of
his configured MAC address/IP address.

Dragonflow needs to add specific rules to allow all the allowed address
pairs.

Port Security Disable
---------------------
Neutron has a feature to disable port security for ML2 plugins [3], even
that Dragonflow is currently not a ML2 plugin, we still would like a way
to disable/enable port security for a certain port.

L2 ARP Supression
-----------------
It is also important to note that with full ARP L2 suppression [2], some of
the features described here are not needed as OVS flows are used
to respond to ARP requests and no ARP traffic should actually reach a VM.
We still need to verify that this also block gratitude ARPs.

Blocking invalid broadcast/multicast traffic
--------------------------------------------
As part of the port security feature we should also prevent traffic loops.
We drop traffic that has the same src and dst ports classified (the src port register
and the dst port register are same).
This scenario happens when we handle broadcast/multicast traffic and just
duplicate packet few times for every port in the broadcast domain or
multicast group.

DHCP protection
---------------
Protection from DHCP DDoS on the controller (DHCP application) is going to be handled
on a different spec that will address controller reliability concerns.

References
==========
[1] http://specs.openstack.org/openstack/neutron-specs/specs/api/allowed_address_pairs.html

[2] https://blueprints.launchpad.net/dragonflow/+spec/l2-arp-supression

[3] https://github.com/openstack/neutron-specs/blob/master/specs/kilo/ml2-ovs-portsecurity.rst