..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==========================
Load Balancer as a Service
==========================

https://bugs.launchpad.net/dragonflow/+bug/1710784

Implement support for Load Balancer as a Service for both L4 (LBaaS v2) and
L7 (Octavia) load balancing.

Problem Description
===================

Load balancing enables OpenStack tenants to load-balance their traffic between
ports.

The Dragonflow implementation should be fully distributed. Therefore, load
balancing decisions should be made on the source compute node. In the case
there is no source compute node, e.g. provider network or DNat, a random
compute node should be selected. In future implementation, a distributed
model can be used here as well.

Note: Neutron API allows specifying a load-balancer _provider_. Dragonflow
will appear as a _provider_.

Currently, Dragonflow supports HA proxy and Octavia implementation.
Any work done implementing this spec should not break that support.
Additionally, if there are load balancers provided both by Dragonflow and
by e.g. Octavia, both should work after this spec is implemented. Therefore,
the implementation of this feature should only handle load-balancers which
have Dragonflow as a provider.

For example, if a tenant selects two load balancers, one with Octavia and one
with Dragonflow as providers, both should work and should not interfere with
one another.

Terminology
===========

This terminology is the same as in the Neutron spec [1]_.

Proposed Change
===============

The following diagram shows a schematic of a client VM connecting to a load-
balanced service.

::

   Compute Node 1
  +--------------------------------------------------+
  |             Load-Balancer                        |
  |                   +                              |
  |                   |        +--------+  +-------+ |
  | +--------+        +--------+Member 1+--+Health-| |
  | |        |        |        +--------+  |Check  | |
  | | Client +--------+                    |Service| |
  | |        |        |        +--------+  |       | |
  | +--------+        +--------+Member 2+--+       | |
  |                   |        +--------+  +-------+ |
  +--------------------------------------------------+
                      |
                      |
                      |Tunnelled Network
   Compute Node 2     |
  +--------------------------------------------------+
  |                   |                              |
  |                   |        +--------+  +-------+ |
  |                   +--------+Member 3+--+Health-| |
  |                            +--------+  |Check  | |
  |                                        |Service| |
  |                                        |       | |
  |                                        |       | |
  |                                        +-------+ |
  +--------------------------------------------------+

Client is a logical port. It can be a VM, vlan trunk, or any other device
that has a Neutron port.

Member 1, Member 2, and Member 3 are all pool members of the same pool.

The client's traffic will be directed to Member 1, Member 2, or Member 3.
Optionally, members 1 and 2 will have higher priority.

Note that the Client can also be on a third compute node, with no
load-balancer members. This does not affect the proposed solution.

The packet will be passed using Dragonflow's regular pipeline,
i.e. setting reg7 to the destination's key, and possibly changing eth_dst,
ip_dst, and the network ID (metadata register).

A Health-Check service will check the health of each member of every pool.
There will be a single Health-Check instance (at most O(1)) per compute
node.  The Health-Check service will encode the destination member's
identifier (the port's unique key) into the IP destination address
(much like the metadata service).

The Load Balancer object listens on its IP, and listeners. Listener
objects listen on a specific protocol and features. Each Listener has
an Endpoint which decides on which protocol to listen, and on some
protocol-specific filters. For example, HTTP endpoints may listen
only for specific request URLs.

Listeners also have a TLS field embedding a TLS object. This object
is used to allow Listeners (and Load Balancers) to terminate TLS
communication. This information is provided by the API, and passed
along the database to the implementation on the compute nodes.

TLS termination should be extensible, i.e. different proxies and key-stores
should be available. As an initial implementation, Barbican will be used
as presented in [2]_.

The Neutron API and objects can be found here [3]_.

The fully distributed architecture should show an improvement in performance.

Models
------

LoadBalancer
~~~~~~~~~~~~

This is the main object describing the load balancer.

   +-----------+--------------------------+-----------------------------------+
   | Name      | Type                     | Description                       |
   +===========+==========================+===================================+
   | id        | String                   | LoadBalancer identifier           |
   +-----------+--------------------------+-----------------------------------+
   | topic     | String                   | Project ID                        |
   +-----------+--------------------------+-----------------------------------+
   | enabled   | Boolean                  | Is the load balancer enabled?     |
   +-----------+--------------------------+-----------------------------------+
   | listeners | ReferenceList<Listener>  | On what protocols/ports to listen?|
   +-----------+--------------------------+-----------------------------------+
   | network   | Reference<LogicalNetwork>| On what network is the VIP?       |
   +-----------+--------------------------+-----------------------------------+
   | subnet    | Reference<Subnet>        | On what subnet is the VIP?        |
   +-----------+--------------------------+-----------------------------------+
   | port      | Reference<LogicalPort>   | On what (virtual) port is the VIP?|
   +-----------+--------------------------+-----------------------------------+
   | ip_address| IPAddress                | What's the VIP?                   |
   +-----------+--------------------------+-----------------------------------+

Endpoint
~~~~~~~~

This object represents an endpoint location. This states what conditions
on the packet are needed to accept the packet for load-balancing. It also
states how the packet needs to be modified (e.g. port number changes)

The Endpoint object should support both L4 and L7 match and action policies.

Need to support protocols tcp, udp, icmp, null (raw?), and http (at least)

TCP or UDP Endpoint:

   +---------------+----------------------+-----------------------------------+
   | Name          | Type                 | Description                       |
   +===============+======================+===================================+
   | protocol      | Enum (UDP, TCP)      | The protocol for this endpoint    |
   +---------------+----------------------+-----------------------------------+
   | ports         | PortRange            | The ports to match on             |
   +---------------+----------------------+-----------------------------------+

ICMP Endpoint:

   +---------------+----------------------+-----------------------------------+
   | Name          | Type                 | Description                       |
   +===============+======================+===================================+
   | protocol      | Enum (PING)          | The protocol for this endpoint    |
   +---------------+----------------------+-----------------------------------+

HTTP Endpoint:

   +--------------+---------------------------+-------------------------------+
   | Name         | Type                      | Description                   |
   +==============+===========================+===============================+
   | protocol     | Enum (HTTP)               | The protocol for this endpoint|
   +--------------+---------------------------+-------------------------------+
   | policies     | ReferenceList<HTTPPolicy> | HTTP match policies           |
   +--------------+---------------------------+-------------------------------+

Where an HTTP policy object is:

   +-----------+---------------------------+----------------------------------+
   | Name      | Type                      | Description                      |
   +===========+===========================+==================================+
   | action    | Embed<Action>             | The action of this policy        |
   +-----------+---------------------------+----------------------------------+
   | enabled   | Boolean                   | Is the policy enabled?           |
   +-----------+---------------------------+----------------------------------+
   | rules     | ReferenceList<HTTPRule>   | The rules when the policy matches|
   +-----------+---------------------------+----------------------------------+

An action can be one of:

Reject action:

   +---------------+------------------------------+---------------------------+
   | Name          | Type                         | Description               |
   +===============+==============================+===========================+
   | action_type   | Enum (Reject)                | The action of this policy |
   +---------------+------------------------------+---------------------------+

Redirect to pool action:

   +-------------+--------------------------+---------------------------------+
   | Name        | Type                     | Description                     |
   +=============+==========================+=================================+
   | action_type | Enum (REDIRECT_TO_POOL)  | The action of this policy       |
   +-------------+--------------------------+---------------------------------+
   | pool        | Reference<Pool>          | The pool to redirect the session|
   +-------------+--------------------------+---------------------------------+

Redirect to URL action:

   +---------------+-------------------------+--------------------------------+
   | Name          | Type                    | Description                    |
   +===============+=========================+================================+
   | action_type   | Enum (REDIRECT_TO_URL)  | The action of this policy      |
   +---------------+-------------------------+--------------------------------+
   | url           | String (Or a URL type)  | The URL to redirect the session|
   +---------------+-------------------------+--------------------------------+

An HTTP Rule object is:

   +----------+-----------------------------+---------------------------------+
   | Name     | Type                        | Description                     |
   +==========+=============================+=================================+
   | operation| Enum (CONTAINS, ...)        | The operation this rule tests   |
   +----------+-----------------------------+---------------------------------+
   | is_invert| Boolean                     | Should the operation be         |
   |          |                             | inverted?                       |
   +----------+-----------------------------+---------------------------------+
   | type     | Enum(COOKIE, FILE_TYPE, ...)| The type of key in the          |
   |          |                             | comparison                      |
   +----------+-----------------------------+---------------------------------+
   | key      | String                      | The key in the comparison       |
   +----------+-----------------------------+---------------------------------+
   | value    | String                      | The literal to compare against  |
   +----------+-----------------------------+---------------------------------+

A policy matches if any rule matches.

"Raw" protocol

   +---------------+---------------+------------------------------------------+
   | Name          | Type          | Description                              |
   +===============+===============+==========================================+
   | protocol      | Enum (RAW)    | The protocol for this endpoint           |
   +---------------+---------------+------------------------------------------+
   | location      | Integer       | The location to start the match          |
   +---------------+---------------+------------------------------------------+
   | value         | String        | The value that should be in the location |
   +---------------+---------------+------------------------------------------+

An endpoint for the raw protocol accepts a packet only if the raw data at
<location> equals <value>.

TLS
~~~

This object contains the information needed for the Listener (or Load Balancer)
to terminate TLS connections [2]_.

   +---------------+--------------------+-------------------------------------+
   | Name          | Type               | Description                         |
   +===============+====================+=====================================+
   | tls-container | String             | TLS container                       |
   +---------------+--------------------+-------------------------------------+
   | sni-container | String             | SNI container                       |
   +---------------+--------------------+-------------------------------------+

Listener
~~~~~~~~

This object represents the listening endpoint of a load balanced service.

   +------------------+-----------------+-------------------------------------+
   | Name             | Type            | Description                         |
   +==================+=================+=====================================+
   | id               | String          |                                     |
   +------------------+-----------------+-------------------------------------+
   | topic            | String          |                                     |
   +------------------+-----------------+-------------------------------------+
   | enabled          | Boolean         | Is the listener enabled?            |
   +------------------+-----------------+-------------------------------------+
   | connection_limit | Integer         | Max number of connections permitted |
   +------------------+-----------------+-------------------------------------+
   | tls              | Embed<TLS>      | Object needed to terminate HTTPS    |
   +------------------+-----------------+-------------------------------------+
   | endpoint         | Embed<Endpoint> | The protocol (and port) to listen on|
   +------------------+-----------------+-------------------------------------+
   | pool             | Reference<Pool> | The pool to load-balance            |
   +------------------+-----------------+-------------------------------------+

Pool
~~~~

A group of members to which the listener forwards client requests.

   +---------------------+--------------------------+-------------------------+
   | Name                | Type                     | Description             |
   +=====================+==========================+=========================+
   | id                  | String                   |                         |
   +---------------------+--------------------------+-------------------------+
   | topic               | String                   |                         |
   +---------------------+--------------------------+-------------------------+
   | enabled             | Boolean                  | Is the pool enabled?    |
   +---------------------+--------------------------+-------------------------+
   | health_monitor      | Reference<HealthMonitor> | Health monitor object   |
   +---------------------+--------------------------+-------------------------+
   | algorithm           | Enum(ROUND_ROBIN, ...)   | supported algorithms    |
   +---------------------+--------------------------+-------------------------+
   | members             | ReferenceList<Member>    | List of ppol members    |
   +---------------------+--------------------------+-------------------------+
   | protocol            | Enum(tcp, udp, icmp, ...)| The protocol supported  |
   |                     |                          | by this pool            |
   +---------------------+--------------------------+-------------------------+
   | session_persistence | Embed<SessionPersistence>| How to detect session   |
   +---------------------+--------------------------+-------------------------+

There are multiple ways to maintain session persistence. The following is an
incomplete list of options.

No session persistence:

   +-----------+--------------------------+-----------------------------------+
   | Name      | Type                     | Description                       |
   +===========+==========================+===================================+
   | type      | Enum (None)              | Must be 'None'                    |
   +-----------+--------------------------+-----------------------------------+

There is no session persistence. Every packet is load-balanced independently.

Source IP session persistence:

   +-----------+--------------------------+-----------------------------------+
   | Name      | Type                     | Description                       |
   +===========+==========================+===================================+
   | type      | Enum (SOURCE_IP)              | Must be 'SOURCE_IP'          |
   +-----------+--------------------------+-----------------------------------+

Packets from the same source IP will be directed to the same pool member.

5-tuple session persistence:

   +-----------+--------------------------+-----------------------------------+
   | Name      | Type                     | Description                       |
   +===========+==========================+===================================+
   | type      | Enum (5-TUPLE)              | Must be '5-TUPLE'              |
   +-----------+--------------------------+-----------------------------------+

Packets with the same 5-tuple will be directed to the same pool member. In the
case of ICMP, or protocols that do not have port numbers, 3-tuples will be
used.

HTTP cookie session persistence:

   +-----------+--------------------+-----------------------------------------+
   | Name      | Type               | Description                             |
   +===========+====================+=========================================+
   | type      | Enum (HTTP_COOKIE) | Must be 'HTTP_COOKIE'                   |
   +-----------+--------------------+-----------------------------------------+
   | is_create | Boolean            | Should the cookie be created by the load|
   |           |                    | balancer?                               |
   +-----------+--------------------+-----------------------------------------+
   | name      | String             | The name of the cookie to use           |
   +-----------+--------------------+-----------------------------------------+

PoolMember
~~~~~~~~~~

This object describes a single pool member.

   +-----------+--------------------------+-----------------------------------+
   | Name      | Type                     | Description                       |
   +===========+==========================+===================================+
   | id        | String                   |                                   |
   +-----------+--------------------------+-----------------------------------+
   | topic     | String                   |                                   |
   +-----------+--------------------------+-----------------------------------+
   | enabled   | Boolean                  |                                   |
   +-----------+--------------------------+-----------------------------------+
   | port      | Reference<LogicalPort>   | The pool members logical port     |
   |           |                          | (containing IP, subnet, etc.)     |
   +-----------+--------------------------+-----------------------------------+
   | weight    | Integer                  | The weight of the member, used in |
   |           |                          | the LB algorithms                 |
   +-----------+--------------------------+-----------------------------------+
   | endpoint  | Embed<Endpoint>          | The endpoint the member listens   |
   |           |                          | on. Used for translation if needed|
   +-----------+--------------------------+-----------------------------------+

Health Monitor
~~~~~~~~~~~~~~

This object represents a health monitor, i.e. a network device that
periodically pings the pool members.

   +------------+---------------------------+---------------------------------+
   | Name       | Type                      | Description                     |
   +============+===========================+=================================+
   | id         | String                    |                                 |
   +------------+---------------------------+---------------------------------+
   | topic      | String                    |                                 |
   +------------+---------------------------+---------------------------------+
   | enabled    | Boolean                   | Is this health monitor enabled? |
   +------------+---------------------------+---------------------------------+
   | delay      | Integer                   | Interval between probes         |
   |            |                           | (seconds)                       |
   +------------+---------------------------+---------------------------------+
   | method     | Embed<HealthMonitorMethod>| Probe method                    |
   +------------+---------------------------+---------------------------------+
   | max_retries| Integer                   | Number of allowed failed probes |
   +------------+---------------------------+---------------------------------+
   | timeout    | Integer                   | Probe timeout (seconds)         |
   +------------+---------------------------+---------------------------------+

Health Monitor Method
~~~~~~~~~~~~~~~~~~~~~

This object states how the health monitor checking is done: e.g. ICMP echo,
or an HTTP request.

Ping method:

   +--------------+----------------------+-----------------------------------+
   | Name         | Type                 | Description                       |
   +==============+======================+===================================+
   | method       | Enum (PING)          | Must be PING                      |
   +--------------+----------------------+-----------------------------------+

This method pings the pool member. It is not available via the Neutron API.

TCP method:

   +--------------+----------------------+-----------------------------------+
   | Name         | Type                 | Description                       |
   +==============+======================+===================================+
   | method       | Enum (TCP)           | Must be TCP                       |
   +--------------+----------------------+-----------------------------------+

This method probes the pool member by trying to connect to it. The port is
taken from the member's endpoint field, or the Listener's endpoint field.

HTTP and HTTPS methods:

   +------------+-------------------------+-----------------------------------+
   | Name       | Type                    | Description                       |
   +============+=========================+===================================+
   | method     | Enum (HTTP, HTTPS)      | Must be HTTP or HTTPS             |
   +------------+-------------------------+-----------------------------------+
   | url        | String (or URL type)    | The URL to probe                  |
   +------------+-------------------------+-----------------------------------+
   | http_method| Enum (GET, POST, ...)   | The HTTP method to probe with     |
   +------------+-------------------------+-----------------------------------+
   | codes      | ReferenceList<Integer>  | The allowed response codes        |
   +------------+-------------------------+-----------------------------------+


Health Monitor Status
---------------------

This object maintains the status of the member. The Health Monitor updates
this table with pool member status, as well as sending updates to Neutron
using e.g. Neutron API or the existing status notification mechanism.


   +--------+--------------------------------+--------------------------------+
   | Name   | Type                           | Description                    |
   +========+================================+================================+
   | member | ID                             | The monitored pool member's ID |
   +--------+--------------------------------+--------------------------------+
   | chassis| ID                             | The name of the hosting chassis|
   +--------+--------------------------------+--------------------------------+
   | status | Enum (ACTIVE, DOWN, ERROR, ...)| The status of the pool member  |
   +--------+--------------------------------+--------------------------------+

Implementation
--------------

Dragonflow will provide an LBaaS service plugin, which will receive LBaaS
API calls, and translate them to Dragonflow Northbound database updates, as
described in the models above.

Neutron API allows to define the provider of the Load-Balancer. Dragonflow
implements the 'Dragonflow' provider, i.e. load balancer application only
implements LoadBalancer instances with 'Dragonflow' as the provider.

The load balancer functionality is implemented with an LBaaS application.

The load balancer application will listen to all events here.

When a load-balancer is created or updated, an ARP, ND, and ICMP
responders (where relevant, and if configured) are created.

Load balancing will be done by the OVS bridge, using OpenFlow Groups or
OpenFlow bundles (see options_). Optionally, the packet will be passed to
the Load Balancer's logical port.

In some cases, OpenFlow is not powerful enough to handle the Endpoint, e.g.
an endpoint for a specific HTTP request URL. In this case, the packet will
be uploaded to the controller, or passed to an external handler via an lport.
See below (l7_) for more details on these options.

When a listener is added, a new flow is created to match the endpoint,
and divert it to the correct Group or Bundle (see options_).

The listener's flow will be added after the security groups table. This
is to allow security group policies to take effect on Load Balancer
distributed ports.

When a pool is added, a new Group or Bundle is created (see options_).

When a pool member is added, it is added to the relevant Group or Bundle
(see options_).

Session persistence will be handled by `learn` flows. When a new session is
detected, a new flow will be installed. This allows the `session_persistence`
method `SOURCE_IP` to be used. Other methods will require sending the packet
to the controller, or to a service connected via a port.

The API also allows session persistence to be done using source IP or HTTP
cookie, created either by the load-balancer or the back-end application.
The first packet of such a connection will be sent to the controller, which
will install a flow for the entire TCP (or UDP) session.

This implementation will add a health monitor service. It will be similar
to existing services (e.g. bgp). It will update the 'service' table once
an interval, to show that it is still alive. It will listen for events on
the health monitor table.

When a health monitor is created, updated, or deleted, the health monitor
service will update itself with the relevant configuration.

The health monitor will be connected to the OVS bridge with a single
interface.  It will send relevant packets to ports by encoding their
unique ID onto the destination IP address (128.0.0.0 | <unique key>). (See
options_)

.. _options:

Option 1: Groups
~~~~~~~~~~~~~~~~

OpenFlow groups allow the definition of buckets. Each bucket has a set of
actions. When the action of a flow is a group, then a bucket is selected,
and the actions of that bucket are executed.

Every pool is a group. Every member of a pool is given a bucket in
the group.

This option may not be supported, since we use OpenFlow 1.3

Option 2: Bundle
~~~~~~~~~~~~~~~~

OpenFlow provides the action `bundle_load`, which hashes the given fields
and loads a selected ofport into the given field.

In this option, `bundle_load` will be given the 5-tuple as fields (eth_src,
eth_dst, ip_src, ip_dst, and ip_proto for ipv4, and ipv6_src, ipv6_dst for
ipv6).

It will load the pool members' lports' unique id (which will be given as if
it is an ofport) into reg7.

Packets will then be dispatched in the standard method in Dragonflow.

Using the `learn` action, it will create a return flow and forward flow to
ensure that packets of the same session are always sent to the same port.

Flows created with `learn` will be given an idle timeout of configurable value
(default 30 seconds). This means flows will be deleted after 30 seconds of
inactivity.

.. _l7:

Option 1: Controller
~~~~~~~~~~~~~~~~~~~~

When an l7 packet is detected, it will be sent to the controller. The
controller will verify that this packet matches an endpoint on that IP address.

If the packet does not match any endpoint, it will be returned to be handled
by the rest of the pipeline (e.g. L2, L3).

If it matches an endpoint, the endpoint actions will be applied. That is, a
pool member will be selected, and the relevant packet mangling will be done.
If a proxy is needed, the packet will be forwarded there, and the proxy will
forward it to the pool member.

Option 2: External Port
~~~~~~~~~~~~~~~~~~~~~~~

When an l7 packet is detected, it will be sent to an OFPort attached to
the OVS bridge. Behind the port is a service that will handle the packet,
terminating the connection if needed, and acting as a proxy.

This service will have to have access to the NB DB for some of the necessary
information.

In some cases, l4 traffic will also be passed to this service, in case
load-balancing algorithms not supported by OVS are used.

In case the packet is not handled by this IP, the service will return the
packet to the OVS bridge using a different OFPort. The bridge will know to
reinject the packet into the right location in the pipeline according to the
source OFPort. If the original service's OFPort is used to send a packet, it
will be treated as a response packet.

Alternatively, the `pkt_mark` header
can be used to mark the packet as a non-lbaas packet.

This is the preferred option.

Health Monitor
~~~~~~~~~~~~~~

The health monitor will use a single instance of HA proxy per compute node.

The HA proxy instance will send probes to peers using their unique_key encoded
in the IP destination field. The eth_dst address may also be spoofed to skip
the ARP lookup stage.

The OVS bridge will detect packets coming from the HA proxy. The LBaaS
application will install flows which update the layer 2 (eth_dst, eth_src),
layer 3 (ip_dst, ip_src), and metadata registers (metadata, reg6, reg7), and
send the packet to the destination member.

Once a port is detected as down, it will be effectively removed from the pool.
It will be marked as down. No new connections will be sent to it.

A configuration option will specify if connections to a downed member are
dropped or re-routed. Since there is no API for this, this will go through
config files until an API is proposed.

Handling Multiple Datatypes
---------------------------

This spec requires the model framework to support a form of polymorphism, e.g.
multiple types of health monitor methods, or multiple types of endpoints.

There are two methods to support this:

1. Union type

2. Factory method

Union type
~~~~~~~~~~

The base class will include all properties of all children classes.

Pros:

* Simple

Cons:

* The model may become very big

* Fields will very likely be abused.

Factory method
~~~~~~~~~~~~~~

Override the base class's `from_*` methods to call the correct child class.

Pros:

* The correct type magically appears

Cons:

* Very complex

* Possibly unintuitive

References
==========

.. [1] https://specs.openstack.org/openstack/neutron-specs/specs/api/load-balancer-as-a-service__lbaas_.html

.. [2] https://wiki.openstack.org/wiki/Network/LBaaS/docs/how-to-create-tls-loadbalancer

.. [3] https://developer.openstack.org/api-ref/load-balancer/v2/index.html
