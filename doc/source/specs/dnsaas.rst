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

Currently neutron reference implementation for internal DNS resolving [#]_ [#]_
spawn a Dnsmasq server for every namespace on the compute node, per tenant
per subnet, that is configured with DHCP server.

Those are the same Dnsmasq services used by the reference implementation for
the DHCP server.
Since Dragonflow use its own DHCP [#]_, currently Dnsmasq is being deployed
only for internal DNS resolving.

Dragonflow can resolve DNS queries locally on each compute node, and prevent
spawning multiple Dnsmasq services per compute node.


Proposed Change
===============

The DNS service contains two main elements:

1. External DNS server (currently exists)

2. Dragonflow DNS application


The DNS application will receive the DNS lookup from the VM.
If the DNS lookup address should resolved to a local address, it will return
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
* Currently this is the prefered option.
Dragonflow will deploy a new service (similar to the Metadata service).
It will resolve DNS lookups for local address, or forward the request to
an external server.
The DNS service address will be added to the default DNS servers offered by
the DHCP application.

::

    +-----------------------------------+
    |                                   |              +-------------+
    |   +-----+         +-------------+ |         +----+ External DNS|
    |   |     |         |             | |         |    +   Service   |
    |   | VM  |         |DF Controller| |         |    +-------------+
    |   +-----+         |    +--------+ |         |
    |      |            |    |DNS App | |         |
    |      |            |    +--------+ |         |
    |      |            |    | DNS    | |         |
    |      |            |    |Service | |         |
    |      |            |    |        | |         |
    |      |            |    |        +-----------+
    |      |VM port     +-------------+ |
    |      |IP 169.254.1.25  | DNS server: 169.254.1.2
    |   +---------------------------+   |
    |   | OVS switch                |   |
    |   +---------------------------+   |
    |                                   |
    +-----------------------------------+

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


Dragonflow data-model impact
============================
Missing fields will be added to the db (provided by neutron):
1. dns_name will be added to the chassis's table
2. domain_name will be added to the subnet's table



References
==========
.. [#] https://docs.openstack.org/neutron/pike/admin/config-dns-int.html

.. [#] https://specs.openstack.org/openstack/neutron-specs/specs/liberty/internal-dns-resolution.html

.. [#] https://github.com/openstack/dragonflow/blob/master/doc/source/distributed_dhcp.rst
