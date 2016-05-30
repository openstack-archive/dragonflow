..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==============================
Allowed address pairs
===============================

https://blueprints.launchpad.net/dragonflow/+spec/allowed-address-pairs

This blueprint describes how to support allowed address pairs for
Dragonflow.

Problem Description
===================
Allowed address pairs feature allows one to add additional ip/mac address
pairs on a port to allow traffic that matches those specified values.

In Neutron original implement, ip address in allowed address pairs could be
a prefix, and this ip address prefix may even not in the subnet of this port's
fixed ip. This wide tolerance will great increase efforts to support allowed
address pairs, and we don't see any requirement for now to using it. So in
dragonflow, we will only support allowed address pairs using ip addresses (not
ip address prefixes) in the same subnet of the port's fixed ip.

In current implement, security module like port security and security group
will restrict packets sent/received from a VM port must have the fixed ip/mac
address of this VM port. Besides, L2 and L3 transmission will forward packets
only according those fixed addresses. Those module should make some changes
to support allowed address pairs.

Proposed Change
===============
A VM port could send or receive packets using the addresses configured in
allowed address pairs. So, in some aspects, allowed address pairs play a role
which is similar with fixed ip/mac address pair in a port, and functional
modules should also handle them like fixed ip/mac address pair.

Port Security
----------------------
Port security should let not only packets with the fixed ip/mac address pair
but also packets with address pairs configured in allowed address pairs field
of a port. That is already done in the blueprint of mac-spoofing-protection.

Security Group
----------------------
Security group module transfrom remote group field in a rule to flows
according ip addresses of VM ports associating with this remote group.
To support allowed address pairs, those IP addresses should include both
fixed ip address and the ip addresses in alowed address pairs.

L2/L3 Lookup
----------------------
As a tenant may configured for the use of VRRP, one or more VM ports could
share a same ip address (and a same mac address in some scenes) in allowed
address pairs. In L2/L3 Lookup table, we could simply send the packets of
which dstination address are this address to all VM ports which have this
address in their allowed address pairs field, or we could only send those
packets to the VM port of which this address is active (VRRP master router).
The later may be a better choice, only if we could know which VM port is the
active one.

Arp Responder
---------------
Because more than one VM ports' allowed address pairs could have a same ip
address but different mac addresses, arp responder can hardly know which mac
address should be reponsed to a arp request to this ip. We could simply
continue to boardcast those arp requests rather than try to response them in
arp table.


References
==========
[1] http://specs.openstack.org/openstack/neutron-specs/specs/api/allowed_addr
ess_pairs.html
[2] http://www.ietf.org/rfc/rfc3768.txt
