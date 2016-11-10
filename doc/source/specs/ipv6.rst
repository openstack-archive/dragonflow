..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==========================
IPv6 Support in Dragonflow
==========================

https://blueprints.launchpad.net/dragonflow/+spec/ipv6

IPv6 and IPv4 have significant differences, not only on the IP address
format, but also on the upper layer protocols. In this specification, we
will discuss the required changes for existing Dragonflow applications,
and required IPv6-only applications. This will help IPv6 networks to
gain the same benefits that IPv4 networks currently gain.


Problem Description
===================

Currently, most of Dragonflow applications and services support only IPv4.
This makes the process of deploying IPv6 network not as easy as deploying
IPv4 network. In order for Dragonflow to be supported fully in IPv6,
Deploying IPv4 and IPv6 networks and VMs must be the same.

Proposed Change
===============

In this spec, the plan is to add IPv6 support to Dragonflow. Specifically,
the plan is to add support for IPv6 to the Dragonflow framework, and
its applications. New IPv6 services, which do not exist in IPv4, will
be added as standalone Dragonflow applications.

The following items are necessary to add IPv6 support for Dragonflow:

* Metadata service

* Neighbor Discovery

* DHCPv6

* L2 (already works)

* L3 (already works)

* Security Groups

The following items are IPv6 features and services which are nice to have:
* ICMPv6 responder (fully implemented)

* IND

* Secure Neighbor Discovery

* Multicast Router Discovery


The following items exist for IPv4 and should not be ported, nor support, IPv6:

* dNAT

* sNAT

* ARP responder


Metadata Service
----------------

Currently Neutron Metadata service does support IPv6 ([1]). When the spec
and its implementation will be finished, as it was done in [2].


Neighbor Discovery
-------------------

Neighbor Discovery [3] relates to different protocols and processes known
from IPv4 that have been modified and expanded. It combines Address
Resolution Protocol (ARP) and ICMP Router Discovery and Redirect.

Neighbor Discovery is used in the ICMv6 protocol to verify there are no
IP collisions, to match IP to MAC addresses, and to provide information
to fellow VMs and routers.

In Dragonflow, the plan is to write a Neighbor & Router Advertisment [4]. It
will be implemented using OpenFlow flows. It will detect neighbor
solicitation requests and respond. In case the packet is something flows
cannot handle, it will be passed to the controller.


DHCPv6
------

In IPv6 there are two non-exclusive modes of DHCPv6 [5]:

1. Stateful

2. Stateless

Stateful DHCPv6 means host configuration with IPv6 assignment (similar
to DHCPv4).
Stateless DHCPv6 means configuring only other network
configurations Dragonflow will support both modes.
Exact implementation will be documented in a future document [6].


Security Groups
---------------

The current implementation supports only IPv4. Since the behavior is the
same, the adjustments will be relatively minor. The changes will affect
mostly on the formating of the IP.


References
==========

* [1] https://bugs.launchpad.net/neutron/+bug/1460177

* [2] https://github.com/openstack/dragonflow/blob/master/doc/source/specs/metadata_service.rst

* [3] https://www.ietf.org/rfc/rfc2461.txt

* [4] https://bugs.launchpad.net/dragonflow/+bug/1480672

* [5] https://tools.ietf.org/html/rfc3315

* [6] https://blueprints.launchpad.net/dragonflow/+spec/dhcpv6-app
