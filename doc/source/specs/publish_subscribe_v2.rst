================================
Publisher Subscriber Refactor v2
================================

https://blueprints.launchpad.net/dragonflow/+spec/pub-sub-v2

This spec is to refactor the pub-sub mechanism to implement
publisher in df-local-controller.

Problem Description
===================

Currently pub/sub mechanism doesn't work in the following scenario:

When enabling port-status driver or automatic port detection for
allow-address-pair, the zeromq pub/sub driver doesn't work. Because
these two applications require the df-local-controller run publishers.
It brings socket bind conflicts when running two publishers on the
same host (one is df-local-controller, the other is df-publisher-service).

If you deploy with redis driver, everything will be well. Because redis-based
pub/sub mechanism doesn't require socket binding.

This bug is dedicated to zeromq based driver and was reported earlier [1].

Moreover this superficial problem will lead to the rest of the mess.

* The port-status driver's name is redis-based, but the implementation
  doesn't have anything to do with redis nb db driver. This driver is possible
  to be the generic one. The gap is that it requires df-local-controller run
  publisher and neutron-server run subscriber.

* The active-port-detection app also requires df-local-controller run publisher.

* We set up publisher port in the common [df] section in the configuration.
  When we run both df-local-controller and df-publisher-service, they read
  the same option to initialize and we don't have the chance to specify
  different port for these services.

* The publisher run on the df-local-controller doesn't register itself
  to nb db. Because the registration is implemented in df-publisher-service,
  not in publisher driver. As a result, the corresponding subscriber cannot
  connect to it via dynamic registration. Instead it only connects publishers
  set up in the configuration, aka publisher_ips. By default, publisher_ips
  contains the local host ip address. So, when you deploy in multi-node,
  the subscriber will not be able to connect to other publishers.

* We implement dynamic registration for df-publisher-service and we also keep
  the old publisher_ips in configuration which leads double registration.

* We initialize publisher and subscriber in api_nb module and determine
  multiproc by is_neutron_server flag. This is not flexible as we need to
  modify the internal states of api_nb to decide which publisher or subscriber
  to use.

The fix of this bug is simple, but it is also a good chance to revisit pub/sub
mechanism.

Proposed Change
===============

One of the solution for this bug is to try to enable multiproc publisher in
df-local-controller when it runs with df-publisher-service. As a result, both
neutron-server and df-local-controller will publish events via ipc to
df-publisher-service and let it distribute event to where the subscriber
locates. It is the fast path but it still hides the potential problems.

In order to achieve this, you need to refactor df-publisher-service and the
multiproc logic. It will greatly introduce complexity in this service.
Moreover, these work won't help make it better, just focusing on this
dedicated bug. According to the original design, the df-publisher-service
is working with neutron-server and help re-distribute its messages to
local controllers. Let's keep it.

The other solution for this bug is to try to refactor the pub/sub to fix all
the issues discussed above one by one. I'd like to provide a more flexible way
to define publisher while maintaining the current df-publisher-service logic.

Configuration Impact
--------------------

[neutron]
publisher_port = 8866
publisher_binding_address = *
pub_sub_use_multiproc = True/False
publisher_multiproc_socket = ...

[controller]
publisher_port = 8867
publisher_binding_address = *
pub_sub_use_multiproc = True/False
publisher_multiproc_socket = ...

API_NB Impact
-------------

* Add constants for role definition, ROLE_NEUTRON_SERVER and
  ROLE_DF_LOCAL_CONTROLLER.

* Pass one of the role constant when initializing api_nb and
  remove the is_neutron_server_flag.

* Check each role and apply different options according to the above section:

  if role == ROLE_NEUTRON_SERVER:
      read pub/sub options from [neutron-server] section
  else role == ROLE_DF_LOCAL_CONTROLLER:
      read pub/sub options from [df_local_controller] section

Publisher Subscriber Impact
---------------------------

* Remove publisher_ips option and logic.

* Move publisher registration codes from df-publisher-service to driver.
  When initializing publisher, it will auto-register itself to nb db,
  along with its role definition.

* When subscriber read nb db, it will filter the role in order to register
  to the right publishers.

Other Impact
------------

* Make api_nb module singleton in df-local-controller. We don't need to initialize
  it each time, for instance, in port-status-driver, just passing its reference.

* Make redis-port-status driver work for all the db drivers.

* Make active port detection work for all the db drivers.

Implementation
==============

Assignee(s)
-----------

Primary assignee:
  `nick-ma-z <https://launchpad.net/~nick-ma-z>`_

References
==========

[1] https://bugs.launchpad.net/dragonflow/+bug/1651643
