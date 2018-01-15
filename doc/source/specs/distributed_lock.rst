================
Distributed lock
================

Problem Description
===================

Currently dragonflow relays on Neutron database for implementing
a distributed lock for protecting Northbound db CUD operations.
For running dragonflow without depend on neutron (use-cases:
direct kuryr support or running with dragonflow
independence api) a distributed lock that not relying
neutron DB should be present.

Proposed solution:
==================

Currently this spec suggest 3 options ,
the purpose is to create a discussion about which
option should be better. when we get to agreement about
one of the options , a full spec should be provided


option 1 - add to db-api "lock" and "unlock" operations
-------------------------------------------------------

2 function will be added to db-api:
  * Acquire-lock
  * Release-lock

And each db driver should implement them.

While in etcd [#]_, redis [#]_ and zookeeper [#]_ distributed-lock
is supported in native way -in cassandra, ramcloud , and rethink it's
not supported natively and require an lock logic implementation above
the current features of the DB. (in cassandra maybe the
"Lightweight Transaction" [#]_ can be used for locks,
and it's possible over Rethink as it's implemented by NoBrainer [#]_ (
a ruby ORM for rethink DB).

pros:
  * The native implantation for redis, etcd and zookeeper.
  * Reuse the northbound db for create the lock
cons:
  * cassandra/rethink/ramcloud  - None native implantation , it's will be hard to
    implement , and it had more chances to bugs.

option 2 - use dedicated db for locks
-------------------------------------

Create a software module that use a dedicate DB for manging the locks.
The db that will used for creating the lock will used in addition to the
northbound db.
The db could be mysql,redis,etcd or zookeeper or any other suitable db.
This DB should be will not be related to the nb_api in any way .

pros:
  * Single code for lock implementation
  * Choose the must appropriate DB to the task.
  * similar to the code today - separate db for locks
cons:
  * Another DB in the system.


option 3 - run a lock algorithm without db
------------------------------------------

There is many distribute locks algorithms , for example :
, paxos [#]_ ,  2PC [#]_  and others (there is interesting discussion
about those algorithms for choosing CAS algorithm for cassandra [#]_).
We need choose suitable and simple algorithm , and it's can be implemented
above ZMQ.

pros:
  * No dependency on DB at all.
cons:
  * Hard to impalement with many corner-cases and potential bugs.








.. [#] https://github.com/coreos/etcd/blob/master/Documentation/dev-guide/api_concurrency_reference_v3.md#service-lock-etcdserverapiv3lockv3lockpbv3lockproto
.. [#] https://redis.io/topics/distlock
.. [#] https://zookeeper.apache.org/doc/r3.3.6/recipes.html#sc_recipes_Locks
.. [#] https://www.datastax.com/dev/blog/lightweight-transactions-in-cassandra-2-0
.. [#] http://nobrainer.io/docs/distributed_locks/
.. [#] http://the-paper-trail.org/blog/consensus-protocols-paxos/
.. [#] https://en.wikipedia.org/wiki/Two-phase_commit_protocol
.. [#] https://issues.apache.org/jira/browse/CASSANDRA-5062
