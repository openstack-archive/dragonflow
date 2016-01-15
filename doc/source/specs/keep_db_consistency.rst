..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

============================================================
Keep DB Consistency between Neutron and Dragonflow - Phase 1
============================================================

The URL of your launchpad Blueprint:

https://blueprints.launchpad.net/dragonflow/+spec/keep-db-consistency

This blueprint proposes the solutions for how to keep data consistency between
Neutron DB and Dragonflow DB. As we know, Neutron DB stores the virtualized
network topology of OpenStack clouds. It is a reliable relational data store
and can be considered as the master DB in Dragonflow distributed architecture.
As a result, the question becomes how to guarantee the atomicity of DB
operations across two distinct kinds of database in the one API session.
Here we will propose a simple and feasible distributed lock solution and
improve it later according to evaluation in production.


Problem Description
===================

Currently, Dragonflow architecture has two type of data stores. One is Neutron
DB responsible for storing virtualized network topology. This database is
relational and all the operations on it are based upon atomic transactions.
It is considered as the master DB of Dragonflow. The other is distributed NoSQL
DB responsible for storing Dragonflow-related topology, the subset of Neutron
DB. It is considered as the slave DB of Dragonflow. Its API, encapsulated by
Dragonflow, lacks of atomic transaction in general which causes inconsistency.

There are several problems related with DB inconsistency in the current
codebase. The pseudo-code to demonstrate the inconsistency is as follows:

* Scenario 1, in Bug [1]:

    with transaction of Neutron DB:
        call Neutron DB API
    call Dragonflow DB API

When an exception is thrown from Dragonflow DB API, however, Neutron DB
transaction is committed. We need to call re-sync to make sure the two DB is
in the same state. This phenomenon is discovered when Dragonflow is
disconnected after Neutron DB transaction is committed.

* Scenario 2, in Bug [2]:

    with transaction of Neutron DB:
        call Neutron DB API
    call _some_operation(...)

    def _some_operation(...):
        call get_key(...)
        update the values.
        call set_key(...)

After Neutron DB is committed, concurrent calling of _some_operation function
will still cause inconsistency, because all the operations in that function are
not atomic. This phenomenon is discovered in multi-node deployments.

Proposed Change
===============

To solve the problems discussed above, the general idea is to introduce a
distributed lock mechanism for core plugin layer. The distributed lock is to
protect the API context and prevent from concurrent write operations on the
same records in the database.

Distributed Lock
----------------

To solve these problems, a SQL-based distributed lock mechanism is introduced.
A carefully-designed SQL transaction is capable of being an external atomic
lock to protect all the dependent database operations both for Neutron DB and
DF distributed NoSQL server in a given API context. This can greatly reduces
the complexity of introducing other sophisticated sychoronization mechanism
from scratch.

The distributed lock is tenant-based and each tenant has its own lock in the
database. Due to this design, we can allow concurrency to a certain degree.

In Neutron plugin:
    When an API is processing:
        Acquire the distributed lock for the Neutron object.
            Start Neutron DB transaction for network operations.
                Do Neutron DB operations.
            Do DF DB operations.
            Emit messages via PUB/SUB.
        Release the distributed lock.

* When creating the distributed lock record, it starts a DB transaction and
inserts a lock record into Neutron DB according to the current object.

* When acquiring the distributed lock, it first issue SELECT-FOR-UPDATE to
check the lock has been obtained or not. If not, it updates the lock state
and commits the transaction. If exception happens, it will re-try it for
several times. If the lock has been obtained, it will wait and re-try.

* If MySQL clustering involves, only one lock transaction will be committed
and others will be deadlocked. Here we introduce DB retry mechanism.
If deadlock exception happens, it will retry it to make sure it will be
committed later.

* Potential Issue: When concurrent write operations on a certain key happen,
due to the inconsistency window of DF DB. If the update on DF DB is always
delayed because the previous operations have already been delayed.
The root cause is that Neutron DB is strongly consistent but DF DB is
eventually consistent. We cannot guarantee the updates on DF DB is committed.

Pseudo Code in Core Plugin
---------------------------

    def CUD_object(context, obj):
        nb_lock = lock_db.DBLock(context.tenant_id)
        with nb_lock:
            with db_api.autonested_transaction(context.session):
                modified_obj = super(Plugin, self).CUD_object(context, obj)
            self.nb_api.CUD_object(name=obj['id'],
                                   topic=obj['obj']['tenant_id'],
                                   modified_obj)
        return modified_obj

* CUD means create, update or delete.

* This can be simplified by a decorator:

    @lock_db.wrap_db_lock()
    def CUD_object(self, context, obj):
        pass

Data Model Impact
-----------------

As noted above, the spec adds a new table for the distributed lock in Neutron
DB. The table is designed as follows:

.. csv-table::
    :header: Attribute,Type,Description

    object_uuid, String, primary key
    lock, Boolean, True means it is locked.
    session_id, String, generated for a given API session
    created_at, DateTime

Work Items
==========

1. Introduce alembic for DB migration. (DONE)
2. Create DB schema for distributed lock. (DONE)
3. Implement distributed lock. (DONE)
4. Protect all the API operations by distributed lock. (DONE)

Potential Improvements
======================

1. The SELECT-FOR-UPDATE consumes much computing resources in clustering
by Galera certification process. This can be improved by a SQL-based
compare-and-swap operation which is currently used in Nova [3].

2. For simplicity, we protect the whole API session by distributed lock.
This is definitely not optimal. We can use distributed lock to only protect
NB-API operations and introduce versioned object and synchronization
mechanism [4]. If the versions in Neutron DB and DF DB are not equal,
we sync the object from Neutron DB to DF DB to guarantee the data is
consistent.

3. The SQL-based lock is not optimal solution. If DF DB provides
atomic operations on a set of read/write operations, we can refactor
the current SQL-based implementation.

4. REMOVE Neutron DB. As a result, we don't need to bother the consistency
of two distinct databases. We only need to make sure a set of read/write
operations of DF DB is atomic to prevent from race due to concurrency.
This solution is appealing but not feasible if we cannot solve the
inconsistent read issue caused by eventual consistency of db backend.

References
==========

[1] https://bugs.launchpad.net/dragonflow/+bug/1529326
[2] https://bugs.launchpad.net/dragonflow/+bug/1529812
[3] http://www.joinfu.com/2015/01/understanding-reservations-concurrency-locking-in-nova
[4] https://blueprints.launchpad.net/dragonflow/+spec/sync-neutron-df-db
