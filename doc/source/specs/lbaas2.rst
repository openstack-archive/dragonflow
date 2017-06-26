..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==========================
Load Balancer as a Service
==========================

Include the URL of your launchpad RFE:

https://bugs.launchpad.net/dragonflow/+bug/example-id

Implement support for Load Balancer as a Service for both L4 (LBaaS v2) and
L7 (Octavia) load balancing.

Problem Description
===================

Load balancing enables OpenStack tenants to load-balance their traffic between
ports.

The Dragonflow implementation should be fully distributed. Therefore, load
balancing decisions are made on the source compute node.

The implementation should also support interoperability with external
load-balancer mechanisms, e.g. Octavia.

Terminology
===========

This terminology is the same as in the Neutron spec [1]_.

Proposed Change
===============

The following diagram shows a schematic of a client VM connecting to a load-
balanced service.

::

   Compute Node
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
   Compute Node       |
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
protocol-specific filters.

The relation between Load Balancers and Listeners is many-to-many. This
means that a Load Balancer (IP) can be assigned several endpoints
(e.g. TCP, UDP, multiple ports). This also means listeners (endpoints)
can be reused.

Listeners also have a TLS field embedding a TLS object. This object
is used to allow Listeners (and Load Balancers) to terminate TLS
communication.

Models
------

LoadBalancer
~~~~~~~~~~~~

This is the main object describing the load balancer.

+-----------+--------------------------+-------------------------------------+
| Name      | Type                     | Description                         |
+===========+==========================+=====================================+
| id        | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| topic     | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| enabled   | Boolean                  |                                     |
+-----------+--------------------------+-------------------------------------+
| listeners | ReferenceList<Listener>  |                                     |
+-----------+--------------------------+-------------------------------------+
| network   | Reference<LogicalNetwork>|                                     |
+-----------+--------------------------+-------------------------------------+
| subnet    | Reference<Subnet>        |                                     |
+-----------+--------------------------+-------------------------------------+
| port      | Reference<LogicalPort>   |                                     |
+-----------+--------------------------+-------------------------------------+
| ip_address| IPAddress                |                                     |
+-----------+--------------------------+-------------------------------------+
| pools     | ReferenceList<Pool>      |                                     |
+-----------+--------------------------+-------------------------------------+

Endpoint
~~~~~~~~

This object represents an endpont location. This states to what conditions
on the packet are needed to accept the packet for load-balancing. It also
states how the packet needs to be modified (e.g. port number changes)

Need to support protocls tcp, udp, icmp, null (raw?), and http (at least)

TLS
~~~

This object contains the information needed for the Listener (or Load Balancer)
to terminate TLS connections [2]_.

+---------------+----------------------+-------------------------------------+
| Name          | Type                 | Description                         |
+===============+======================+=====================================+
| tls-container | String               |                                     |
+---------------+----------------------+-------------------------------------+
| sni-container | String               |                                     |
+---------------+----------------------+-------------------------------------+

Listener
~~~~~~~~

This object represents the listening endpoint of a load balanced service.

+------------------+-------------------+-------------------------------------+
| Name             | Type              | Description                         |
+==================+===================+=====================================+
| id               | String            |                                     |
+------------------+-------------------+-------------------------------------+
| topic            | String            |                                     |
+------------------+-------------------+-------------------------------------+
| enabled          | Boolean           |                                     |
+------------------+-------------------+-------------------------------------+
| conenction_limit | Integer           |                                     |
+------------------+-------------------+-------------------------------------+
| tls              | Embed<TLS>        |                                     |
+------------------+-------------------+-------------------------------------+
| endpoint         | Embed<Endpoint>   |                                     |
+------------------+-------------------+-------------------------------------+
| pool             | Reference<Pool>   |                                     |
+------------------+-------------------+-------------------------------------+

Pool
~~~~

A group of members to which the listener forwards client requests.

+---------------------+--------------------------+-----------------------+
| Name                | Type                     | Description           |
+=====================+==========================+=======================+
| id                  | String                   |                       |
+---------------------+--------------------------+-----------------------+
| topic               | String                   |                       |
+---------------------+--------------------------+-----------------------+
| enabled             | Boolean                  |                       |
+---------------------+--------------------------+-----------------------+
| health_monitor      | Reference<HealthMonitor> |                       |
+---------------------+--------------------------+-----------------------+
| algorithm           | Enum                     | (supported algorithms)|
+---------------------+--------------------------+-----------------------+
| members             | ReferenceList<Member>    |                       |
+---------------------+--------------------------+-----------------------+
| protocol            | Enum                     | (tcp, upd, icmp, null)|
+---------------------+--------------------------+-----------------------+
| session_persistence | Enum                     | (tcp, upd, icmp, null)|
+---------------------+--------------------------+-----------------------+

PoolMember
~~~~~~~~~~

This object describes a single pool member.

+-----------+--------------------------+-------------------------------------+
| Name      | Type                     | Description                         |
+===========+==========================+=====================================+
| id        | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| topic     | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| enabled   | Boolean                  |                                     |
+-----------+--------------------------+-------------------------------------+
| address   | IPAddress                |                                     |
+-----------+--------------------------+-------------------------------------+
| subnet    | Reference<Subnet>        |                                     |
+-----------+--------------------------+-------------------------------------+
| weight    | Integer                  |                                     |
+-----------+--------------------------+-------------------------------------+
| endpoint  | Embed<Endpoint>          |                                     |
+-----------+--------------------------+-------------------------------------+

Health Monitor
~~~~~~~~~~~~~~

This object represents a health monitor, i.e. a network device that
periodically pings the pool members.

+--------------+--------------------------------+-----------------------+
| Name         | Type                           | Description           |
+==============+================================+=======================+
| id           | String                         |                       |
+--------------+--------------------------------+-----------------------+
| topic        | String                         |                       |
+--------------+--------------------------------+-----------------------+
| enabled      | Boolean                        |                       |
+--------------+--------------------------------+-----------------------+
| delay        | Integer                        |                       |
+--------------+--------------------------------+-----------------------+
| method       | Embed<HealthMonitorMethod>     |                       |
+--------------+--------------------------------+-----------------------+
| max_retries  | Integer                        |                       |
+--------------+--------------------------------+-----------------------+
| timeout      | Integer                        |                       |
+--------------+--------------------------------+-----------------------+

How to implement? Assume HAProxy, how to connect to vswitch with proper
information? (pkt_mark, which should be enough to contain enough info, or encode
on IP, like in metadata)

Health Monitor Method
~~~~~~~~~~~~~~~~~~~~~

This object states how the health monitor checking is done: e.g. ICMP echo,
or an HTTP request.

To be subclassed by: HTTP, ICMP

Implementation
--------------

The load balancer application only implements the 'Dragonflow' LBaaS
provider.

The load balancer functionality is implemented with an LBaaS application.

The load balancer application will listen to all events here.

When a load-balancer is created or updated, and ARP, ND, and ICMP
responders (where relevant, and if configured) are created.

Load balancing will be done by the OVS bridge, using OpenFlow Groups or
OpenFlow bundles (see below). Optionally, the packet will be passed to
the Load Balancer's logical port.

In some cases, OpenFlow is not powerful enough to handle the Endpoint, e.g.
an endpoint for a specific HTTP request URL. In this case, the packet will
be uploaded to the controller.

When a listener is added, a new flow is created to match the endpoint,
and divert it to the correct Group or Bundle (see below).

The listener's flow will be added after the security groups table. This
is to allow security group policies to take effect on Load Balancer
distributed ports.

When a pool is added, a new Group or Bundle is created (see below).

When a pool member is added, it is added to the relevant Group or Bundle
(see below).

Session persistence will be handled by `learn` flows. When a new session is
detected, a new flow will be installed. This allows the `session_persistence`
method `SOURCE_IP` to be used. Other methods will require sending the packet
to the controller, or to a service connected via a port.

This implementation will add a health monitor service. It will be similar
to existing services (e.g. bgp). It will listen for events on the health
monitor table.

When a health monitor is created, updated, or deleted, the health monitor
service will update itself with the relevant configuration.

The health monitor will be connected to the OVS bridge with a single
interface.  It will send relevant packets to ports by encoding their
unique ID onto the destination IP address (128.0.0.0 | <unique key>). (See
below)

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

It will load the lports unique id (which will be given as if it is an ofport)
into reg7.

Packets will then be dispatched in the standard method in Dragonflow.

Using the `learn` action, it will create a return flow and forward flow to
ensure that packets of the same session are always sent to the same port.

Flows created with `learn` will be given an idle timeout of configurable value
(default 30 seconds). This means flows will be deleted after 30 seconds of
inactivity.

Health Monitor
--------------

The health monitor will use a single instance of HA proxy per compute node.

The HA proxy instance will send probes to peers using their unique_key encoded
in the IP destination field. The eth_dst address may also be spoofed to skip
the ARP lookup stage.

The OVS bridge will detect packets coming from the HA proxy. The LBaaS application
will install flows which update the layer 2 (eth_dst, eth_src), layer 3 (ip_dst, ip_src),
and metadata registers (metadata, reg6, reg7), and send the packet to the
destination member.

Handling Multiple Datatypes
---------------------------

This spec requires the model framework to support a form of ploymorphism, e.g.
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
