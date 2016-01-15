..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==================================================
Keep DB Consistency between Neutron and Dragonflow
==================================================

The URL of your launchpad Blueprint:

https://blueprints.launchpad.net/dragonflow/+spec/keep-db-consistency

This blueprint proposes the solutions for how to keep data consistency between
Neutron DB and Dragonflow DB. As we know, Neutron DB stores the virtualized
network topology of OpenStack clouds. It is a reliable relational data store
and can be considered as the master DB in Dragonflow distributed architecture.
As a result, the question becomes how to synchronize the slave DB (Dragonflow
distributed NoSQL data store) from the master DB (Neutron data store). In this
design, we will propose a simple and feasible distributed lock solution and
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
full-sync mechanism for Neutron plugin layer and introduce a distributed
lock mechanism for API-NB layer. Finally, all the Neutron objects are versioned.

The full-sync mechanism is to synchonize all the virtual topology from
Neutron DB to DF distributed NoSQL server when the data is inconsistent.
It runs at the background and checks the consistency periodically.

The distributed lock is to protect the API context and prevent from
concurrent write operations on the same records in the database.

The versioned object is to check the two objects are identical or not. This
mechanism is also useful for PUB/SUB.

Full-Sync Mechanism
-------------------

In Neutron plugin:
    When initialize the neutron df plugin:
        Run compare-db to identify the difference between two DBs.
        Run update-df-db to make it be synchronized.

    Run a df-db-health-checker greenthread or external process:
    (this should be an option for df-plugin):
        Periodically run compare-db and call update-df-db if necessary.

If multiple neutron-servers start with full-sync simultaneously, the database
is still in chaos. As a result, the whole database should be locked in
advance by the distributed lock.

Distributed Lock
----------------

To solve these problems, a SQL-based distributed lock mechanism is introduced.
A carefully-designed SQL transaction is capable of being an external atomic
lock to protect all the dependent database operations both for Neutron DB and
DF distributed NoSQL server in a given API context. This can greatly reduces
the complexity of introducing other sophisticated sychoronization mechanism
from scratch.

The distributed lock is object-based and each object has its own lock in the
database. Due to this design, we can allow concurrency to a certain degree.

In Neutron plugin:
    When an API is processing:
        Start Neutron DB transaction for network operations.
            Do Neutron DB operations.

        Start Neutron DB transaction for updating version.
            Read the version from Neutron DB.
            Increment the version of the corresponding Neutron object.

        Acquire the distributed lock for the Neutron object.
            Compare the version from Neutron DB and the version from DF DB.
            If they are equal:
                Do DF DB operations.
                Emit messages via PUB/SUB.
            Else:
                raise BadVersionException.
        Release the distributed lock.

* When creating the distributed lock, it starts a DB transaction and inserts
a lock record into Neutron DB according to the current object.

* When acquiring the distributed lock, it first issue SELECT-FOR-UPDATE to
check the lock has been obtained or not. If not, it updates the lock state
and commits the transaction. If the row is not found, it will wait and re-try
it several times because it indicates that other DB session has obtained the
lock on the same object.

According to the design of this SQL-based lock, we doesn't take advantage of
subtransactions, because it will fail when re-read the lock row. Re-read the
row inside the transaction will continue to not return the new value under
Neutron default transaction isolation level (REPEATABLE). To deal with this
problem, we just re-issue a new transaction for re-read the lock row and
update it.

* If MySQL clustering involves, only one lock transaction will be committed
and others will be deadlocked. Here we introduce DB retry mechanism provided
by oslo.db. If deadlock exception happens, it will retry it to make sure it
will be committed later.

* Potential Issue: When concurrent write operations on a certain key happen,
due to the inconsistency window of DF DB. If the previous operations have
already been delayed for a partition of the DF DB cluster, some controller
may always get the out-of-date object from those delayed servers. The root
cause is that Neutron DB is strongly consistent but DF DB is eventually
consistent. We cannot guarantee the updates on each server in DF DB cluster
is finally committed.

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

As noted above, this spec adds a new table for versioned objects in Neutron DB.
The table is designed as follows:

.. csv-table::
    :header: Attribute,Type,Description

    object_uuid, String, primary key
    object_type, String, object type
    version, Integer, the version starts from 0.
    created_at, DateTime


Work Items
==========

1. Introduce alembic for DB migration.
2. Create DB schema for distributed lock and versioned objects.
3. Implement distributed lock and versioned objects.
4. Protect all the API operations by distributed lock.
5. Implement synchronization mechanism [3].

References
==========

[1] https://bugs.launchpad.net/dragonflow/+bug/1529326
[2] https://bugs.launchpad.net/dragonflow/+bug/1529812
[3] https://blueprints.launchpad.net/dragonflow/+spec/sync-neutron-df-db
