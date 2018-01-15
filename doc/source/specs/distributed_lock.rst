=========================
Plugable Distributed lock
=========================

Problem Description
===================

Currently Dragonflow relies on Neutron database for the implementation
of distributed locks to protect the Northbound DB CUD operations.
In order to run Dragonflow independently from Neutron (use-cases:
direct Kuryr support or running with Dragonflow independent api)
a distributed locking mechanism that does not rely on Neutron DB
should be present.

Proposed solution:
==================

Implement a plugable lock mechanism.

In a similar way to current Pub/Sub mechanism , an api
for locking and unlocking will be presented and in-tree or
out-of-tree modules could implement the lock in different
ways.

This methodology keeping the plugable design of Dragonflow, and
enable flexibility in the deployment. for example a deployments
that runs with neutron could use the current neutron-db-lock logic, while
deployments without neutron could use different drivers that suit
to the dragonflow distributed-db.

API
---

.. code-block:: python

  """" Obtain the distributed DB lock

  :param rules: object_id - object that the lock should
                applied on
  :param block: if True will block until lock obtain else
                if the lock isn't free an exception will
                be raised
  """
  def lock(object_id, block=True):
    pass

  """Release the lock for object

  :param: object_id that the lock applied on
  """
  def unlock(object_id):
    pass


Drivers:
--------

In the first stage the current DB-lock logic should be implemented as
a driver. In addition drivers that implements locks by redis [1]_,
etcd [2]_ and zookeeper [3]_ could be easy to implement as those dbs
have a builtin support for distributed-locks , and it's
could be nice if deployment's that uses those databases as their northbound
DB could use the same database for the distributed lock.

.. [#] https://github.com/coreos/etcd/blob/master/Documentation/dev-guide/api_concurrency_reference_v3.md#service-lock-etcdserverapiv3lockv3lockpbv3lockproto
.. [#] https://redis.io/topics/distlock
.. [#] https://zookeeper.apache.org/doc/r3.3.6/recipes.html#sc_recipes_Locks
