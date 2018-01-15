================
Distributed lock
================

Problem Description
===================

Currently Dragonflow relies on Neutron database for the implemention
of distributed locks to protect the Northbound DB CUD operations.
In order to run Dragonflow independently from Neutron (use-cases:
direct Kuryr support or running with Dragonflow independent api)
a distributed locking mechanism that does not rely on Neutron DB
should be present.

Proposed solution:
==================

Currently this spec suggests 3 alternatives, and
the purpose is to create a discussion about which
option is better. When we decide which of options
is better, a full spec should be provided


Option 1 - add "lock" and "unlock" operations to db-api
-------------------------------------------------------

2 function will be added to db-api:
  * Acquire-lock
  * Release-lock

Each db driver should implement them.

While in etcd [#]_, redis [#]_ and zookeeper [#]_ distributed-locks
are supported in native way - but in cassandra, ramcloud, and rethinkDB
it is not supported natively and requires a lock logic implementation
on top of the current features of the DB.
For cassandra the "Lightweight Transaction" [#]_ may be used for locks,
and for rethinkDB locks are implemented by NoBrainer [#]_ (a ruby ORM
for rethinkDB).

Pros:
  * Native implantation for redis, etcd and zookeeper.
  * Reuse the northbound DB to create the lock
Cons:
  * cassandra/rethinkDB/ramcloud  - Non-native implantation, it will be hard to
    implement, and it increases the chances for bugs.

Option 2 - use dedicated db for locks
-------------------------------------

Create a software module that uses a dedicated DB for managing the locks.
The DB that will be used for creating the lock, in addition to the
northbound db.
This DB could be mysql, redis, etcd, zookeeper or any other suitable DB.
This DB will not be related to the nb_api DB in any way.

Pros:
  * Single code for locks implementation
  * Choose the most appropriate DB for the task.
  * similar to the code today - separate DB for locks
Cons:
  * Yet another DB in the system.


Option 3 - run a lock logic without a DB
----------------------------------------

There are many distributed locks algorithms, for example :
paxos [#]_ ,  2PC [#]_  and others (there is an interesting discussion
about using these algorithms for choosing CAS algorithm for cassandra [#]_).
We need to choose a suitable and simple algorithm, which may be implemented
on top of ZMQ.

Pros:
  * No dependency on a DB at all.
Cons:
  * Hard to impalement with many corner-cases and potential bugs.








.. [#] https://github.com/coreos/etcd/blob/master/Documentation/dev-guide/api_concurrency_reference_v3.md#service-lock-etcdserverapiv3lockv3lockpbv3lockproto
.. [#] https://redis.io/topics/distlock
.. [#] https://zookeeper.apache.org/doc/r3.3.6/recipes.html#sc_recipes_Locks
.. [#] https://www.datastax.com/dev/blog/lightweight-transactions-in-cassandra-2-0
.. [#] http://nobrainer.io/docs/distributed_locks/
.. [#] http://the-paper-trail.org/blog/consensus-protocols-paxos/
.. [#] https://en.wikipedia.org/wiki/Two-phase_commit_protocol
.. [#] https://issues.apache.org/jira/browse/CASSANDRA-5062
