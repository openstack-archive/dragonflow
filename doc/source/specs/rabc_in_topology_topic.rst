..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===================================================================
Support RBAC based multi-tenants in selective topology distribution
===================================================================

# TODO: add bp link

Problem Description
===================

The selective topology distribution brings several advantages in large
deployment environment.

* The data of subscribed topic will be cached locally. It makes the Dragonflow
  controller doesn't have to cache all the data, and saves the memory in the
  host, which has Dragonflow controller running.

* The Dragonflow controller will only subscribe to the topic that it concerns.
  Comparing to subscribe all the changes, this improves the performance of
  Dragonflow controller.

* Using topic to manage data is easier when amount of data is huge.

Currently, selective topology distribution uses tenant ID of resources as
topic. A resource will only be published to the Dragonflow controllers, which
have subscribed to resource's tenant ID. Neutron RBAC(role based access
control) can share resources with other tenants. This means that the normal
users in other tenants can use the resources that don't belong to their own
tenants. And from the Dragonflow point of view, Dragonflow controller that
subscribes to tenant B, might also be interested in resource in tenant A.
Current implementation of selective topology distribution can't achieve that.

[#]_ https://specs.openstack.org/openstack/neutron-specs/specs/liberty/rbac-networks.html

A feasible workaround to use Dragonflow with multi-tenants scenarios, is to
disable selective topology distribution. This will lose the advantages
mentioned above.

NOTE: The tenant administrator can use resources across tenants without
specifying RBAC. This spec will not take that scenario into account. This spec
will focus on normal users use resources across tenants based on RBAC.

Proposed Change
===============

The proposed change will base on the current implementation of selective
topology distribution.

Tenant ID will still be used as the topic in Dragonflow Database and
publish/subscribe architecture.

The Dragonflow ml2 mechanism driver will subscribe the RBAC CRUD events from
OpenStack Neutron side. When RBAC about a resource is created/updated, the
topic field of that resource will be updated in Dragonflow Northbound Database.
The resource will also be published to the channel of newly added tenant.
Assume QoS policy is in tenant A, and now it has been shared to tenant B by
RBAC. The event of QoS policy now will be published to tenant A and tenant B.

::

                                             +--------------+
                                         +---> Subscriber A |
     +---------+                         |   +--------------+
     | QoS msg |                         |
     +----+----+          +-----------+  |
          |          +----> Tenant  A +--+   +--------------+
     +---->------+   |    +-----------+  +--->              |
     | Publisher +---+                       | Subscriber B |
     +-----------+   |    +-----------+  +--->              |
                     +----> Tenant  B +--+   +--------------+
                          +-----------+  |
                                         |
                                         |   +--------------+
                                         +---> Subscriber C |
                                             +--------------+

If the target tenant of RBAC is `*`, the resource will be broadcast to all
channels. For the resource that has `shared` attribute as True, there will be
a RBAC rule for that resource automatically. The target tenant in that RBAC
rule will be `*`. So, by supporting RBAC in Dragonflow, shared resources can
be used across all tenants.

For the network that has `router:external` attribute as True, there will be a
RABC rule for that network automatically. The target tenant in that RBAC rule
will be `*`, which means all tenants can use the so called external network.
In most scenarios, we won't have one external network for each tenant. By
supporting RBAC in Dragonflow, the external network will be shared across
multiple tenants. So that multiple tenants can share external network to
create router gateway or floating IP.


Configuration Impact
--------------------

None

NB Data Model Impact
--------------------

Change the topic field of current Northbound DB models from a string to a list
of tenant ID. If there is no RBAC, the topic field will be a one element list.
Otherwise, the topic field will be list of related tenant ID.

Publisher Subscriber Impact
---------------------------

There will be no change in Subscriber. Publisher will be changed to be able to
send message to multiple channels. This means the `send_event` in Publisher
will accept a list or a set of topics.

Dragonflow DB CLI Impact
------------------------

None

Dragonflow Applications Impact
------------------------------

None

Installed flows Impact
----------------------

None

Implementation
==============

Assignee(s)
-----------

Primary assignee:
  `xiaohhui <https://launchpad.net/~xiaohhui>`_

Work Items
----------

#. Change the topic field of Northbound DB to a list of string.
#. Change the Publisher to accept multiple topics.
#. Subscribe RBAC event in Dragonflow ml2 mechanism driver, and change topic
   list of resource according to RBAC event.
