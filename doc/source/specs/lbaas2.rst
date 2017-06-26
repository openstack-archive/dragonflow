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

A detailed description of the problem:

* For a new feature this should be use cases. Ensure you are clear about the
  actors in each use case: End User vs Deployer

* For a major reworking of something existing it would describe the
  problems in that feature that are being addressed.

Note that the RFE filed for this feature will have a description already. This
section is not meant to simply duplicate that; you can simply refer to that
description if it is sufficient, and use this space to capture changes to
the description based on bug comments or feedback on the spec.


Rational
========

* Interoperability - allow lbaas implementations both in DF, or as a VM/container

Proposed Change
===============

Models
------

LoadBalancer
~~~~~~~~~~~~

This is the main object describing the load balancer. It has the following
fields:

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
| flavor    | ???                      |                                     |
+-----------+--------------------------+-------------------------------------+
| provider  | ???                      |                                     |
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

Listener
~~~~~~~~

This object represents the listening endpoint of a load balanced service.

+-----------+--------------------------+-------------------------------------+
| Name      | Type                     | Description                         |
+===========+==========================+=====================================+
| id        | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| topic     | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| enabled   | Boolean                  |                                     |
+-----------+--------------------------+-------------------------------------+
| conenction_limit | Integer | |
+-----------+--------------------------+-------------------------------------+
| pool      | Reference<Pool>          |
+-----------+--------------------------+-------------------------------------+
| tls       | ???          |
+-----------+--------------------------+-------------------------------------+
| load_balancers | ReferenceList<LoadBalancer>          |
+-----------+--------------------------+-------------------------------------+
| endpoint  | Endpoint (embedded, reference?)
+-----------+--------------------------+-------------------------------------+

Pool
~~~~

A group of members to which the listener forwards client requests.


+-----------+--------------------------+-------------------------------------+
| Name      | Type                     | Description                         |
+===========+==========================+=====================================+
| id        | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| topic     | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| enabled   | Boolean                  |                                     |
+-----------+--------------------------+-------------------------------------+
| health_monitors | ReferenceList<HealthMonitor> |                                     |
+-----------+--------------------------+-------------------------------------+
| algorithm | Enum (supported algorithms) |                                     |
+-----------+--------------------------+-------------------------------------+
| members   | ReferenceList<Member> |                                     |
+-----------+--------------------------+-------------------------------------+
| protocol   | Enum (tcp, upd, icmp, null) | Why do we need this twice? |
+-----------+--------------------------+-------------------------------------+
| provider   | Enum (dragonflow) (only?) | |
+-----------+--------------------------+-------------------------------------+
| subnet   | Reference<Subnet> | |
+-----------+--------------------------+-------------------------------------+
| vip   | ??? | |
+-----------+--------------------------+-------------------------------------+

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
| endpoint  | Endpoint (embedded, reference?)
+-----------+--------------------------+-------------------------------------+

Health Monitor
~~~~~~~~~~~~~~

This object represents a health monitor, i.e. a network device that
periodically pings the pool members.

+-----------+--------------------------+-------------------------------------+
| Name      | Type                     | Description                         |
+===========+==========================+=====================================+
| id        | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| topic     | String                   |                                     |
+-----------+--------------------------+-------------------------------------+
| enabled   | Boolean                  |                                     |
+-----------+--------------------------+-------------------------------------+
| delay     | Integer                  |                                     |
+-----------+--------------------------+-------------------------------------+
| method    | Reference<HealthMonitorMethod> |                               |
+-----------+--------------------------+-------------------------------------+
| max_retries| Integer |                               |
+-----------+--------------------------+-------------------------------------+
| pool      | Reference<Pool> |                               |
+-----------+--------------------------+-------------------------------------+
| timeout   | Integer |                               |
+-----------+--------------------------+-------------------------------------+

How to implement? Assume HAProxy, how to connect to vswitch with proper
information? (pkt_mark, which should be enough to contain enough info, or encode
on IP, like in metadata)

Health Monitor Method
~~~~~~~~~~~~~~~~~~~~~

???

To be subclassed by: HTTP, ICMP


Implementation
--------------

The load balancer application only implements the 'Dragonflow' LBaaS provider.

The load balancer functionality is implemented with an LBaaS application, named
lb_app.LBApp.

The load balancer application will listen to pool member events.

When a member is added

There are two implementation options: groups and bundles

The load balancer application receives a

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

haproxy
-------

References
==========
