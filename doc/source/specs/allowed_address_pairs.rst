..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=====================
Allowed address pairs
=====================

https://blueprints.launchpad.net/dragonflow/+spec/allowed-address-pairs

This blueprint describes how to support allowed address pairs for
dragonflow.

Problem Description
===================
Allowed address pairs feature allows one port to add additional IP/MAC address
pairs on that port to allow traffic that matches those specified values.

In Neutron reference implementation, IP address in allowed address pairs could
be a prefix, and the IP address prefix might not be in the port's fixed IP
subnet. This wide tolerance will greatly increase efforts to support allowed
address pairs, and we don't see any requirement for now to using it. So in
Dragonflow, we will only support allowed address pairs using IP addresses (not
IP address prefixes) in the same subnet of the port's fixed IP.

In current implementation, security modules like port security and security
group will require that packets sent/received from a VM port which must have the
fixed IP/MAC address of this VM port. Besides, L2 and L3 transmission will
forward packets only according to those fixed addresses. Those modules should
make some changes to support allowed address pairs.

Proposed Change
===============
A VM port could send or receive packets using the addresses configured in
allowed address pairs. In some aspects, allowed address pairs plays a role
which is similar with fixed IP/MAC address pair in a port, and functional
modules should also handle them like fixed IP/MAC address pair.

Port Security
-------------
Port security module should allow packets with the fixed IP/MAC address pair
and also packets with address pairs configured in allowed address pairs field
of a port. That is already done in the blueprint of mac-spoofing-protection.

Security Group
--------------
The security group module transforms the remote group field in a rule to
flows according to IP addresses of VM ports associated with the remote group.
To support allowed address pairs, those IP addresses should include both
fixed IP address and the IP addresses in allowed address pairs.

L2/L3 Lookup
------------
One or more VM ports could share the same IP address (and the same MAC address
in some scenarios) in allowed address pairs. In L2/L3 lookup table, we could
simply send the packets of which destination address is this address to all
VM ports which have this address in their allowed address pairs field,
but that will cause extra bandwidth cost if there are only few VMs actually
using the IP/MAC address in the allowed address pairs field of its port.

A alternative way is sending those packets only to the ports of the VMs who
actually using this IP/MAC. We can distinguish those VMs by receiving its
gratuitous ARP packets of this IP/MAC from their ports, or by periodically
sending ARP requests to the IP and receiving the corresponding ARP replies.
Once those active VMs have been detected, local controllers should save this
information in NB DB and publish it. When L2/L3 APPs receive this notification,
they could install flows to forward packets to the ports of those active VMs
like they do for fixed IP/MAC.

In particularly, if there is only one VM who could use the IP/MAC among VMs
who have this IP/MAC in allowed address pairs field of their ports, the
processes of L2/L3 APPs to install those flows could be simpler. Because
this is a more common usage of allowed address pairs (for example, VRRP),
we only support this situation in Dragonflow as the first step.

In Dragonflow, we propose to support both the first "broadcast way" and the
latter "detectation way", and add an option in the configuration for users to
choose one of them.

ARP Responder
-------------
Because more than one VM ports' allowed address pairs could have the same IP
address but different MAC addresses, ARP responder can hardly know which MAC
address should be responded to an ARP request to this IP. We could simply
continue to broadcast those ARP requests, or we could only use the detected
MAC address of the active VM's port to reply those ARP requests, if the active
VMs mentioned above was detected.


References
==========
[1] http://specs.openstack.org/openstack/neutron-specs/specs/api/allowed_addr
ess_pairs.html
[2] http://www.ietf.org/rfc/rfc3768.txt
