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
Allowed address pairs feature allows one to add additional IP/MAC address
pairs on a port to allow traffic that matches those specified values.

In Neutron reference implementation, IP address in allowed address pairs could
be a prefix, and the IP address prefix might not be in the port's fixed IP
subnet. This wide tolerance will greatly increase efforts to support allowed
address pairs, and we don't see any requirement for now to using it. So in
dragonflow, we will only support allowed address pairs using IP addresses (not
IP address prefixes) in the same subnet of the port's fixed IP.

In current implementation, security modules like port security and security
group will require that packets sent/received from a VM port must have the
fixed IP/MAC address of this VM port. Besides, L2 and L3 transmission will
forward packets only according those fixed addresses. Those modules should
make some changes to support allowed address pairs.

Proposed Change
===============
A VM port could send or receive packets using the addresses configured in
allowed address pairs. In some aspects, allowed address pairs play a role
which is similar with fixed IP/MAC address pair in a port, and functional
modules should also handle them like fixed IP/MAC address pair.

Port Security
----------------------
Port security module should allow packets with the fixed IP/MAC address pair
and also packets with address pairs configured in allowed address pairs field
of a port. That is already done in the blueprint of mac-spoofing-protection.

Security Group
----------------------
The security group module transforms the remote group field in a rule to
flows according IP addresses of VM ports associated with the remote group.
To support allowed address pairs, those IP addresses should include both
fixed IP address and the IP addresses in allowed address pairs.

L2/L3 Lookup
----------------------
One or more VM ports could share a same IP address (and a same MAC address in
some scenarios) in allowed address pairs. In L2/L3 Lookup table, we could
simply send the packets of which destination address is this address to all
VM ports which have this address in their allowed address pairs field.

ARP Responder
---------------
Because more than one VM ports' allowed address pairs could have a same IP
address but different MAC addresses, ARP responder can hardly know which MAC
address should be responded to an ARP request to this IP. We could simply
continue to broadcast those ARP requests rather than try to response them in
ARP table.


References
==========
[1] http://specs.openstack.org/openstack/neutron-specs/specs/api/allowed_addr
ess_pairs.html
[2] http://www.ietf.org/rfc/rfc3768.txt
