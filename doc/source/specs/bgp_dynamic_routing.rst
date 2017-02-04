..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===================
BGP dynamic routing
===================

https://blueprints.launchpad.net/dragonflow/+spec/bpg-dynamic-routing

Border Gateway Protocol (BGP) is a standardized gateway protocol designed to
exchange routing and reachability information among autonomous systems.

BGP dynamic routing in OpenStack enables advertisement of self-service network
prefixes to physical network devices that support BGP, thus removing the
conventional dependency on static routes. The feature relies on address scopes
[#]_ in OpenStack Neutron.

.. [#] http://docs.openstack.org/newton/networking-guide/config-address-scopes.html

Problem Description
===================

Dragonflow doesn't support address scope now, nor does it support BGP dynamic
routing. BGP dynamic routing in OpenStack can run as a pair of plugin and agent
along with Dragonflow deployed. But it could not advertise the route of
floating IP correctly. The virtual router in Dragonflow will be viewed as a
legacy router by OpenStack Neutron. And BGP dynamic routing will use the IP
address of router gateway as the floating IP's next-hop if it is in a legacy
router. However, the floating IPs in Dragonflow are distributed, and can't be
accessed by router gateway.

Meanwhile, running BGP agents which are highly coupled with OpenStack Neutron
is not something Dragonflow favors.

Proposed Change
===============

Support BGP dynamic routing as an application in Dragonflow. Omit the
functionality of address scope for now. Just treat address scope as a logic
concept.

Basically, BGP dynamic routing needs to advertise 2 classes of routes in
Dragonflow.

#. Host routes for floating IP addresses. Floating IPs in Dragonflow do
   stateless NAT and exchange packets with external bridge directly. So,
   the external bridge where the floating IPs can be accessed from. And the
   IP address of external bridge should be the next-hop of host route.
#. Prefix routes for directly routable tenant networks with address scopes.
   If tenant networks are in the same address scope as external network,
   Neutron router will directly route the packets of them to external network,
   instead of NAT the packets. This is the functionality of address scope, but
   it is naturally supported in Dragonflow, thanks to the fact that Dragonflow
   uses Neutron L3 agents to host the router gateway port. The next-hop of
   prefix routes should be the IP address of router gateway port. The router
   gateway port is where the routable tenant networks can be accessed from.

The BGP dynamic routing itself is not a distributed service. A BGP router
should work for an autonomous system and advertise routes for an autonomous
system. The implementation in Dragonflow will also not think it as a
distributed service. This means all routes will be gathered together and be
advertised together.

However, the BGP peer connection can be redundant. So, it is possible to run
multiple BGP applications in different Dragonflow chassis at the same time.
There is benefit to do so. If one host with BGP application is down, other
hosts with BGP application can still advertise the routes. But it is not
recommended to run BGP application in every host in a huge cluster. This will
create lots of BGP connections to peer BGP router, and increase the load of
peer BGP router dramatically.

BGP dynamic routing in OpenStack can't learn dynamic routes from peer BGP
router now. To make things simple, the implementation in this spec will also
not consider learning dynamic routes. Only advertising routes will be
considered.

NB Data Model Impact
--------------------

Add a new string field called *external_ip* to Chassis in Dragonflow Northbound
Database. This field will be used as the next-hop of floating IP host route.

Technically speaking, *external_ip* should be the IP address of external bridge
of external network. But it could be any IP address that Dragonflow chassis
own in practice. Since the IP addresses are in a routing domain. So, the default
value of this field will be local IP of Dragonflow chassis.

Two new data models will be defined. They are BGP speaker and BGP peer.

BGP speaker
~~~~~~~~~~~

::

    +------------------------+---------------------------------------------+
    |    Attribute Name      |               Description                   |
    +========================+=============================================+
    | id                     |   Identify                                  |
    +------------------------+---------------------------------------------+
    | name                   |   Name of the BGP speaker                   |
    +------------------------+---------------------------------------------+
    | topic                  |   Tenant ID of BGP speaker                  |
    +------------------------+---------------------------------------------+
    | local_as               |   The local autonomous system ID            |
    +------------------------+---------------------------------------------+
    | peers                  |   The BGP peers of this speaker             |
    +------------------------+---------------------------------------------+
    | routes                 | The routes that this speaker will advertise |
    +------------------------+---------------------------------------------+
    | ip_version             |    The IP version of this BGP speaker       |
    +------------------------+---------------------------------------------+

The BGP dynamic routing in OpenStack will generate advertise routes when
needed. The implementation here will just store the advertise routes in
Northbound Database for use. This means the routes will be re-calculated
every time a related change takes place.

BGP peer
~~~~~~~~

::

    +------------------------+---------------------------------------------+
    |    Attribute Name      |               Description                   |
    +========================+=============================================+
    | id                     |   Identify                                  |
    +------------------------+---------------------------------------------+
    | name                   |   Name of the BGP peer                      |
    +------------------------+---------------------------------------------+
    | topic                  |   Tenant ID of BGP peer                     |
    +------------------------+---------------------------------------------+
    | peer_ip                |   IP address of BGP peer router             |
    +------------------------+---------------------------------------------+
    | remote_as              |   The autonomous system ID of BGP peer      |
    +------------------------+---------------------------------------------+
    | auth_type              |   Authentication type of BGP peer           |
    +------------------------+---------------------------------------------+
    | password               |   Password of BGP peer                      |
    +------------------------+---------------------------------------------+

Configuration Impact
--------------------

Add a new configuration option, *bgp_router_id*, which is 32-bit BGP
identifier, typically an IPv4 address owned by the system running the BGP
application.

Add a new configuration option, *external_ip*. It is an IPv4 address, which
will be used as the next-hop of floating IP's host route.

Dragonflow Applications Impact
------------------------------

A new application for BGP will be added. The application will based on
*ryu.services.protocols.bgp* to implement the functionality of BGP dynamic
routing. That is to say, all the actual BGP work will be done by ryu library.

When BGP speaker has BGP peers and routes to advertise, any change to routes
will cause the BGP application to advertise or withdraw routes. The changes to
BGP peers will cause BGP application to update the BGP peer connection.

Neutron Service Plugin Impact
-----------------------------

A customized service plugin for BGP dynamic routing in Dragonflow will be
created. The Neutron Database and Dragonflow Northbound Database will be
updated in the plugin. And the events of BGP changes will be published from
the plugin.

Implementation
==============

Assignee(s)
-----------

Primary assignee:
  `xiaohhui <https://launchpad.net/~xiaohhui>`_

Work Items
----------

#. Add data models for BGP.
#. Add configurations for BGP.
#. Implement the Neutron service plugin for BGP.
#. Implement the application for BGP.
