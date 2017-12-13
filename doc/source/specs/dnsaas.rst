..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 https://creativecommons.org/licenses/by/3.0/legalcode

=========================
Internal Dns As A Service
=========================

https://bugs.launchpad.net/dragonflow/+bug/1738195

The DNS service enables users to look up their instances and external services
using the Domain Name System (DNS)


Problem Description
===================

Currently Neutron reference implementation for internal DNS resolving [#]_ [#]_
spawns a Dnsmasq server for every namespace on the compute node, per tenant
per subnet, that is configured with DHCP server.

Those are the same Dnsmasq services used by the reference implementation for
the DHCP server.
Since Dragonflow uses its own DHCP [#]_, currently Dnsmasq is being deployed
only for internal DNS resolving.

Dragonflow can resolve DNS queries on with one service per compute node,
and prevent spawning multiple Dnsmasq services per compute node.


Proposed Change
===============

The DNS service contains two main elements:

1. External DNS server (currently exists)

2. Dragonflow DNS application


The DNS application will receive the DNS lookup request from the VM.
If the DNS lookup address should be resolved to a local address, it will return
the local address.
Otherwise, it will forward the lookup to the External DNS server.

IP overlapping
--------------
Different VMs on different tenants can have identical IPs.
Resolving DNS query for local address will be done only for IPs relevant to
the VM's subnet and tenant.


Possible Implementations
========================
Deploying new service
---------------------

* Currently this is the preferred option.

Dragonflow will deploy a new service (similar to the Metadata service).
It will resolve DNS lookups for local address, or forward the request to
an external server.
The DNS service address will be added to the default DNS servers offered by
the DHCP application.
Currently the DNS service address will be the same as the router.

::

    +-----------------------------------+
    |                                   |              +-------------+
    |   +-----+         +-------------+ |         +----+ External DNS|
    |   |     |         |             | |         |    +   Service   |
    |   | VM  |         |DF Controller| |         |    +-------------+
    |   +-----+         |             | |         |
    |      |            |             | |         |
    |      |            +-------------+ |         |
    |      |            |      DNS    | |         |
    |      |            |     Service | |         |
    |      |            |             | |         |
    |      |            |             +-----------+
    |      |VM port     +-------------+ |
    |      |IP 169.254.1.25  | DNS server: 169.254.1.2
    |   +---------------------------+   |
    |   | OVS switch                |   |
    |   +---------------------------+   |
    |                                   |
    +-----------------------------------+

Pros:

* Overload on the service wont affect the performance of the main df-controller

* Creates separation between the "Control" (the controller),
  and the "Data" parts (the application) of Dragonflow.
  By that, it creates sort of Service-Injection on top of Dragonflow.

Cons:

* Different implementation and deployment than the other apps in Dragonflow
  (with the Metadata app as an exception)


Deploying a DNS application
---------------------------
Dragonflow will "hijack" any outgoing DNS lookups to external DNS services.
If the address can be resolved locally, a response packet will be constructed
and returned.
Otherwise, the packet will continue to its original destination.

::

    +-----------------------------------+
    |                                   |              +-------------+
    |   +-----+         +-------------+ |         +----+ External DNS|
    |   |     |         |             | |         |    +   Service   |
    |   | VM  |         |DF Controller| |         |    +-------------+
    |   +-----+         |    +--------+ |         |
    |      |            |    |DNS App | |         |
    |      |            |    |        | |         |
    |      |            |    |        | |         |
    |      |            |    |        +-----------+
    |      |VM port     +-------------+ |
    |      |IP 169.254.1.25  | DNS server: 8.8.8.8
    |   +---------------------------+   |
    |   | OVS switch                |   |
    |   +---------------------------+   |
    |                                   |
    +-----------------------------------+

Pros

* Similar implementation and deployment to other apps in Dragonflow
  (with the Metadata app as an exception)

Cons

* Overload on the DNS service will affect the local controller performance


Dragonflow data-model impact
============================
Additional table will be created: DNSaaS.
It will contain two lists:

* The first list will create a mapping of domain_name and a link to the to the
  relevant subnet.

::

     DomainName
     +--------------+
     |              |
     | subnet       |
     |              |
     | domain_name  |
     |              |
     +--------------+


* The second list will create a mapping of dns_name and matching lport.

::

     DnsName
     +---------------+
     |               |
     | lport         |
     |               |
     | dns_name      |
     |               |
     +---------------+



The missing information will be provided by Neutron.


Action items
============

1. Deploy a new service from the controller, listening on a new virtual port

2. Capture DNS lookup and process it (can be done with [#]_.
   Will require adding this library to requirements)

3. Resolve query, or send lookup to an external DNS service.

4. Unittest, fullstack, and tempest tests (if exist)


References
==========
.. [#] https://docs.openstack.org/neutron/pike/admin/config-dns-int.html

.. [#] https://specs.openstack.org/openstack/neutron-specs/specs/liberty/internal-dns-resolution.html

.. [#] https://github.com/openstack/dragonflow/blob/master/doc/source/distributed_dhcp.rst

.. [#] https://github.com/cmouse/pdns-remotebackend-python
