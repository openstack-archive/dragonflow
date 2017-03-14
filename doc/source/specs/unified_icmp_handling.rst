 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=================================
Unified ICMP / TTL handling in L3
=================================

 https://blueprints.launchpad.net/dragonflow/+spec/unified-icmp-handeling

This spec aims to unitify TTL handling for DNAT application and L3 routing,
and simplify DNAT app to use existing L3 and provider networks infrastructure.

Problem Description
===================

At this moment, our DNAT implements its own provider network access and
performs its routing in and out of tenant network. This forces it to handle
its own ICMP cases separately.  TODO

Proposed Change
===============

We propose the following changes:
 * Simplify ICMP / TTL handling by unifying it to a single app or
   lib.
 * Transform DNAT app to become a translation unit and rely on L3 app to
   perform the required routing (which will obsolete the need for TTL handling)
 * Use provider network to forward packets in and out of floating ports.

Using floating ports
--------------------

We would like to bind floating ports of floating ips to the chassis which host
the actual VM ports, and that way make the apps (including provider app) aware
of those ports.

Once we have floating ports as local ports in the provider network, we can
forward their traffic to the L3 tables as if it was regular ports. This will
interconnect VMs in provider network and VMs with floating IPs.


DNAT
----

DNAT app will be simple, as now we only need to insert flows into EGRESS_TABLE
(where packets will go post L2_LOOKUP_TABLE) that translate IP_DST, and
forward it to the L3_TABLE for routing.

::

     Ingress:

   +------+  set reg7  +---------+  remap dst   +---------+
   | LOCAL|            |  LOCAL  |              |         |
   | L2   +------------>  EGRESS +-------------->   L3    |
   |      |            |         |              |         |
   +------+            +---------+              +---------+

     Egress:

   +------+             +---------+ restore dst +---------+
   |      |             | PROVIDER|             | PROVIDER|
   |  L3  +-------------> EGRESS  +-------------> L2      |
   |      |             |         |             |         |
   +------+             +---------+             +---------+


TTL treatment
-------------

Since DNAT no longer decrements IP's TTL, all TTL expired treatment will be
done by L3 app.

ICMP translation for NAT apps
-----------------------------
Both SNAT and DNAT need to handle thier inbound and outbound ICMP error
messages, and translate the addresses in the embedded packet.
We propose adding a new NAT-aware app that will intercept all ICMP error
packets and preform the needed translations for both DNAT and SNAT.
