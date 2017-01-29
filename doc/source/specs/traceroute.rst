..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==================
Traceroute support
==================

https://blueprints.launchpad.net/dragonflow/+spec/traceroute-support

Traceroute is a handy network diagnostic tool. Network administrators use
this tool most commonly in their day to day activities. It can provide the
following informations of network:

#. The entire path that a packet travels through
#. Names and identity of routers and devices in the path
#. Network Latency taken to send and receive data to each devices on the path

Problem Description
===================

The virtual routers in Dragonflow don't support traceroute well. When a
detecting packet of traceroute goes through virtual router, you will most
likely get an asterisk from traceroute's output. That means traceroute doesn't
get the expected response from router. More details will be provided in the
following description.

Proposed Change
===============

Supporting traceroute is to support the network functionalities behind it.
Traceroute mainly depends on the TTL(Time To Live) field in the Internet
Protocol. Traceroute will send IP packets with increasing TTL and expect
each router in the network path to reply with an ICMP Time Exceeded message.
By using that message, traceroute can know the information of router in the
network path.

For each router, that will require it to decrease TTL of IP packets when it
routes them. Meanwhile, that will also require each router to discard the
original IP packet and reply an ICMP Time Exceeded message, when the TTL is
invalid. An invalid TTL means its value is not bigger than zero. The details
are defined at RFC1812[#]_.

.. [#] https://tools.ietf.org/html/rfc1812

There are 3 kinds of implementations of traceroute. They are based on UDP, TCP
and ICMP respectively. Different implementations send different IP packets to
detect the network packets. For UDP implementation, traceroute expects the
destination to return an ICMP Destination Unreachable Message. For TCP
implementation, traceroute expects the destination to return an ICMP
Destination Unreachable Message or a SYN/ACK packet. For ICMP implementation,
traceroute expects the destination to return an ICMP echo reply.

Since it is distributed virtual routers in Dragonflow, there is no concrete
router ports. If the destination of traceroute is virtual router ports, they
should response with ICMP Destination Unreachable Message.

The ICMP error message should contain at least 28 bytes of original datagram's
data, according to RFC792[#]_. And traceroute depends on the original
datagram's data to match the detecting IP packets. So the virtual routers in
Dragonflow should also copy the data to the ICMP messages mentioned above.

.. [#] https://tools.ietf.org/html/rfc792

The virtual routers in Dragonflow are also NAT(network address translation)
devices. The NAT here refers to one-one NAT, which is floating IP in
Dragonflow. As mentioned above, the ICMP error message will contain original
datagram's data. It is an embedded packet. According to RFC5508[#]_, NAT
devices should also revert the IP of embedded packet. Or else, it will be
an invalid ICMP packet. Since the header embedded packet will change, its
checksum will be re-calculated when encoded.

.. [#] https://tools.ietf.org/html/rfc5508

A valid ICMP Time Exceeded message should looks like:

::

    02:58:24.390013 IP (tos 0xc0, ttl 63, id 55039, offset 0, flags [none], proto ICMP (1), length 74)
        172.24.4.1 > 20.0.0.12: ICMP time exceeded in-transit, length 54
            IP (tos 0x0, ttl 1, id 6596, offset 0, flags [DF], proto UDP (17), length 46)
            20.0.0.12.51016 > 192.168.31.94.33438: UDP, length 18

Dragonflow controller impact
----------------------------

The virtual switch should be configured to packet-in invalid TTL packets. So
that the Dragonflow controller applications can handle the TTL invalid packets
accordingly. This feature is available in OpenFlow 1.3[#]_. It is also
available in OpenFlow 1.2 with different configuration. To make things simple,
this spec will not cover OpenFlow 1.2.

.. [#] https://www.opennetworking.org/images/stories/downloads/sdn-resources/onf-specifications/openflow/openflow-spec-v1.3.0.pdf

Dragonflow Applications Impact
------------------------------

Because some packets will be sent to Dragonflow controller, the DDoS attack
should be taken into account. When the rate of packet-in is high, proper
OpenFlow rules will be added to drop the packet.

L3 proactive application
~~~~~~~~~~~~~~~~~~~~~~~~

Add packet-in handler to handle TTL invalid packets. The packet-in handler will
also reply UDP/TCP packets with ICMP Destination Unreachable Message.

L3 application
~~~~~~~~~~~~~~

The same as L3 proactive application

DNAT application
~~~~~~~~~~~~~~~~

Add packet-in handlers to handle TTL invalid packets. This includes handler for
ingress NAT packets and handler for egress NAT packets. Both handlers will also
do NAT to the IP of embedded packets of ICMP error message.

Installed flows
---------------

Ingress NAT Table
~~~~~~~~~~~~~~~~~

::

    priority=high,icmp,nw_dst=fip,icmp_type=11 actions=mod_dl_src:gw_mac,mod_dl_dst:vm_mac,dec_ttl,mod_nw_dst:vm_ip,(packet-in controller)
    priority=high,icmp,nw_dst=fip,icmp_type=3 actions=mod_dl_src:gw_mac,mod_dl_dst:vm_mac,dec_ttl,mod_nw_dst:vm_ip,(packet-in controller)

These two flows matche ICMP Time Exceeded message and ICMP Destination
Unreachable Message. Do NAT to the ICMP packets and then packet-in the
packets to controller, where the IP of embedded packets will be reverted.

Egress NAT Table
~~~~~~~~~~~~~~~~

::

    priority=high,icmp,metadata=network_uid,nw_src=vm_ip,icmp_type=11 actions=mod_dl_src:fip_mac,mod_dl_dst:br-ex_mac,mod_nw_src:fip,(packet-in controller)
    priority=high,icmp,metadata=network_uid,nw_src=vm_ip,icmp_type=3 actions=mod_dl_src:fip_mac,mod_dl_dst:br-ex_mac,mod_nw_src:fip,(packet-in controller)

These two flows matche ICMP Time Exceeded message and ICMP Destination
Unreachable Message. Do NAT to the ICMP packets and then packet-in the
packets to controller, where the IP of embedded packets will be reverted.

L3 lookup Table
~~~~~~~~~~~~~~~

::

     priority=high,tcp,metadata=network_uid,nw_dst=router_port_ip actions=(packet-in controller)
     priority=high,udp,metadata=network_uid,nw_dst=router_port_ip actions=(packet-in controller)

These two flows matche UDP and TCP packets to router port, and reply with
ICMP Destination Unreachable Message.

Implementation
==============

Assignee(s)
-----------

Primary assignee:
  `xiaohhui <https://launchpad.net/~xiaohhui>`_

Work Items
----------

#. Configure virtual switch(i.e. br-int) to packet-in TTL invalid packets.
#. Add common function to generate ICMP Time Exceeded message, and apply the
   function to L3 proactive application, L3 application and DNAT application.
#. Add flows to L3 lookup table to packet-in UDP and TCP packets, and reply
   with ICMP Destination Unreachable Message.
#. Add flows to Ingress NAT table and Egress NAT table, and do NAT to embedded
   packet of ICMP error message.
#. Add rate limiter to each packet-in handler.
