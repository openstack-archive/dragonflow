..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

========================================================
Support multi-tenants in selective topology distribution
========================================================

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
topic. This fits perfectly in the VPC(virtual private cloud) scenario. In a
VPC, all resources comes from one tenant. But as [#]_ described, if there
are multiple VPCs in one tenant, using tenant ID as topic will cause redundant
event and redundant cache.

.. [#] ./selective_topo_dist.rst

OpenStack Neutron, as the current Northbound interface of Dragonflow, itself
has a more sophisticated way to manage tenant. Administrator in any tenant
can basically view and use any resource in the current Neutron scope. With
the consideration of RBAC(role based access control), normal user can use
resource in other tenants. So, operating resources across multiple tenants is
legal from Neutron side.

But using tenant ID as topic in selective topology distribution, will not work
in such scenarios. The resources in different tenants don't know each other.
Resources are not subscribed to the changes of resources in other tenants.
Dragonflow controller will not cache resources in irrelevant tenants.

Now, Dragonflow doesn't have the information of Keystone user, nor does it have
any information of RBAC. With these information, it is possible to use tenant
ID as topic in multi-tenants scenarios. But things will become overwhelming
complex.

An alternative to use Dragonflow in multi-tenants scenarios, is to disable
selective topology distribution. This will lose the advantages mentioned above.

Proposed Change
===============

The proposed change will not change the essence of selective topology
distribution. And the proposed change will still keep the possibility to use
tenant ID as topic.

There are a couple of options for the change:

Use Network ID as topic
-----------------------

OpenStack Neutron has several basic resources. They are port, subnet and
network. All other resources are associated to basic resources. Port, subnet
and network have many-to-one relationship. From this point of view, network
can be seen as the root of all other resources.

For the basic resources(i.e. port and network), the topic will be the network
ID, which can be obtained from their attributes. And the topic is singular.

For other resources, for example QoS policy, it will be pulled when the port
is online from Southbound, if it is associated to a port. Its topic will be
updated to contain the network ID of the port. In the case of the QoS is used
by ports in different networks, the topic of QoS will be plural. So, when the
QoS is updated from Northbound API, the change might be published to multiple
channels::

                                             +--------------+
                                         +---> Subscriber A |
     +---------+                         |   +--------------+
     | QoS msg |                         |
     +----+----+          +-----------+  |
          |          +----> Network A +--+   +--------------+
     +---->------+   |    +-----------+  +--->              |
     | Publisher +---+                       | Subscriber B |
     +-----------+   |    +-----------+  +--->              |
                     +----> Network B +--+   +--------------+
                          +-----------+  |
                                         |
                                         |   +--------------+
                                         +---> Subscriber C |
                                             +--------------+

Pros:
* Easy to maintain the topic of resources.
* Less channels to publish when a resource updates.

Cons:
* Still can't prevent sending message to irrelevant subscriber. For example, if
  QoS is associated with port A, all the hosts that have port in the same
  network as port A will accept the QoS message.

Use chassis ID as topic
-----------------------

Since the hosts that have Dragonflow controller running will eventually accept
the published message. Host itself can be used as the topic of selective
topology distribution.

When a port is online from Southbound, all its related resources will be
registered to local host. And in return, the chassis ID of local host will be
added to the topic of the related resources.

For the port, because its change is concerned by all other ports in the same
network. Its topic will be the same as its network. So that the change of
ports can be broadcasted to the L2 domain::

                          +-----------+    +--------------+
                     +----> Chassis A +----> Subscriber A |
     +---------+     |    +-----------+    +--------------+
     | QoS msg |     |
     +----+----+     |    +-----------+    +--------------+
          |          +----> Chassis B +----> Subscriber B |
     +---->------+   |    +-----------+    +--------------+
     | Publisher +---+
     +-----------+   |    +-----------+    +--------------+
                     +----> Chassis C +----> Subscriber C |
                          +-----------+    +--------------+

Pros:
* The message of resource can be published to the only hosts that care about
  it.
* Easy to understand the concept. Each host is a separate channel.

Cons:
* When a resource updates, there will be more channels to publish the change.


The topology module in Dragonflow will be refactor. The tenant specified code
will be extracted into a separate module. A new module for selected solution
will be added. The topology module will load corresponding module
according to the topic strategy.

Configuration Impact
--------------------

Add a new configuration option, *topic_type*. Its possible value will be tenant
or network ID or chassis ID, depends on which option is selected. When it is
specified as `tenant`, Dragonflow will behave the same as current selective
topology distribution. 

NB Data Model Impact
--------------------

Change the topic field of current Northbound DB models from a string to a list
of string. When use `tenant` as topic_type, the topic will always be a one
element list, whose value is the tenant of current resource.

Rename the method parameter in Northbound DB drivers from topic to tenant. So
that when topic_type is `tenant`, nothing will be affect. Besides, topic should
be the concept in Publisher and Subscriber, not in the Northbound DB.

Since there will be possibility to update topic of same resource from different
hosts, the write operation of Northbound Database should be multi-processes safe.

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

#. Rename the parameter of Northbound DB driver from topic to tenant.
#. Change the topic field of Northbound DB to a list of string.
#. Extract the tenant specific routine from topology and move them into a new
   module.
#. Add the module to use network ID as topic.
#. Add the configure option to select the topic strategy.
#. Change the Publisher to accept mutiple topics.
