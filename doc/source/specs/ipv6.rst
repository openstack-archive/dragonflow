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
deploying IPv4 and IPv6 networks and VMs must be the same.


Proposed Change
===============

In this document, the plan is to add IPv6 support to Dragonflow. Specifically,
the plan is to add support for IPv6 to the Dragonflow framework, and
its applications. New IPv6 services, which do not exist in IPv4, will
be added as standalone Dragonflow applications.

The following items are necessary to add IPv6 support for Dragonflow:

 Trivial changes:

 * Neighbor Discovery

 * L2 (already works)

 * L3 (already works)

 * Security Groups

 A separate specification document is required for:

 * Metadata service

 * DHCPv6


.. _remaining:

The following items are IPv6 features and services which are nice to have:

* ICMPv6 responder (fully implemented)

* Inverse Neighbor Discovery

* Secure Neighbor Discovery

* Multicast Router Discovery

* Floating IPs (currently not supported by `Open Stack Networking <http://docs.openstack.org/draft/networking-guide/config-ipv6.html>`_)


The following items exist for IPv4 and should not be ported, nor support, IPv6:

* dNAT

* sNAT

* ARP responder


Metadata Service
----------------

Currently Neutron Metadata service does not support IPv6 [#]_ [#]_.
When the Neutron's specification and implementation will be completed,
a dedicated spec will be written as it was done in `IPv4 Metadata Service <metadata_service.rst>`_.


Neighbor Discovery
-------------------

Neighbor Discovery [#]_ relates to different protocols and processes known
from IPv4 that have been modified and expanded. It combines Address
Resolution Protocol (ARP) and ICMP Router Discovery and Redirect.

Neighbor Discovery is used in the ICMPv6 protocol to verify there are no
IP collisions, to match IP to MAC addresses, and to provide information
to fellow VMs and routers.

In Dragonflow, the plan is to write a Neighbor & Router Advertisement [#]_. It
will be implemented using OpenFlow flows. It will detect neighbor
solicitation requests by identifying the packet type [#]_. The application will
build the response with the requested Link-Layer Address.

::

     icmp6,ipv6_dst=1::1,icmp_type=135 actions=load:0x88->NXM_NX_ICMPV6_TYPE[],move:NXM_NX_IPV6_SRC[]->NXM_NX_IPV6_DST[],mod_dl_src:00:11:22:33:44:55,load:0->NXM_NX_ND_SLL[],IN_PORT

In case the packet is something flows cannot handle, it will be passed
to the controller.


DHCPv6
------

In IPv6 there are two non-exclusive modes of DHCPv6 [#]_:

1. Stateful Address Autoconfiguration

2. Stateless Address Autoconfiguration (SLAAC) [#]_

Stateful DHCPv6 means host configuration with IPv6 assignment (similar
to DHCPv4).
Stateless DHCPv6 means only configuration information to hosts (DNS, NTP, etc),
and not perform any address assignment.
Dragonflow will support both modes.
Exact implementation will be documented in a future document [#]_.


Security Groups
---------------

The current implementation supports only IPv4. Since the behavior is the
same, the adjustments will be relatively minor.
The changes will affect mostly on the conversion of the IP to integer,
and building the flow with IPv6 fields.


Timeframe
=========
Neighbor Discovery, DHCPv6 and the Security Groups are planned to be
completed by the end of Ocata.
The Metadata Service implementation is depending on Neutron.
For the remaining_ items there is no estimated cycle.


References
==========

.. [#] https://bugs.launchpad.net/neutron/+bug/1460177

.. [#] https://review.openstack.org/#/c/315604/

.. [#] https://www.ietf.org/rfc/rfc2461.txt

.. [#] https://bugs.launchpad.net/dragonflow/+bug/1480672

.. [#] https://tools.ietf.org/html/rfc4861#section-13

.. [#] https://tools.ietf.org/html/rfc3315

.. [#] https://tools.ietf.org/html/rfc2462

.. [#] https://blueprints.launchpad.net/dragonflow/+spec/dhcpv6-app
