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
distributed NoSQL data store) to the master DB (Neutron data store). In this
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
        call set_key(...)
        call get_key(...)
        call set_key(...)
        call delete_key(...)

After Neutron DB is committed, concurrent calling of _some_operation function
will still cause inconsistency, because all the operations in that function are
not atomic. This phenomenon is discovered in multi-node deployments.

Proposed Change
===============

To solve the problems discussed above, the general idea is to introduce a
full-sync mechanism for Neutron plugin layer and introduce a distributed
lock mechanism for API-NB layer.

The full-sync mechanism is to synchonize all the virtual topology from
Neutron DB to DF distributed NoSQL server when the data is inconsistent.
It runs at the background and checks the consistency periodically.

The distributed lock is to protect the API context and prevent from
concurrent write operations on the same records in the database.

Finally, the northbound db also needs to be refactored. The reason why
this inconsistency problem is discovered is that the DF DB doesn't have
a dedicated table for subnet. When updating subnet, it updates the
corresponding network table 'lswitch', which increases the frequency
of concurrent read/write operations on the same key. In order to reduce
the possibility of race condition, we need to refactor the db schema.

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

Distributed Lock Mechanism
--------------------------

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
        Create the distributed lock from Neutron DB.
        Create the same distributed lock to DF DB.

        Start Neutron DB transaction.
        If the lock-id exists in Neutron DB
            Do Neutron DB operations.
            Release the distributed lock in Neutron DB.
        Else
            Rollback Neutron DB transaction.

        If the lock-id exists in DF DB
            Do DF DB Operations.
            Emit messages via PUB/SUB.
            Release the distributed lock in DF DB.
        Else
            Resync database.

* When creating the distributed lock, it starts a DB transaction and updates
Neutron DB and DF DB in the same transaction to prevent from inconsistency. As
a result, the DB operations are both conducted or failed.

* If some exception happens during Neutron DB operations, the Neutron DB will
be rolled back.

* If some exception happens during DF DB operations, the Neutron DB doesn't
need to be rolled back. Instead, it will invoke re-sync from Neutron DB to
DF DB because the DF DB has dirty data.

* An API context may involve multiple NB-APIs, so we need to cache and execute
them in the top-level function. To achieve this, the DF DB operations are
queued in the function calling chain, and they are conducted in the Neutron
plugin API layer. We implement a local action queue to store DF DB operations
in a given API context.

Data Model Impact
-----------------

As noted above, the spec adds a new table for the distributed lock in Neutron
DB. A migration script will be provided. The table is designed as follows:

.. csv-table::
    :header: Attribute,Type,Description

    tenant_id, String, primary key
    lock_id, String, lock id generated for a given API session

As noted above, this spec adds a new table for subnet object in DF DB. The
table is designed as follows:

.. csv-table::
    :header: Table,Key,Value

    lswitch, network-id, {'subnets': ['subnet-id']}
    lsubnet, subnet-id, {subnet-properties}

Work Items
==========

1. Introduce alembic for DB migration.
2. Create DB schema for distributed lock.
3. Implement distributed lock.
4. Protect all the API operations by distributed lock.
5. Implement synchronization mechanism [3].
6. Refactor DF DB schema and all the related DF DB operations.

References
==========

[1] https://bugs.launchpad.net/dragonflow/+bug/1529326
[2] https://bugs.launchpad.net/dragonflow/+bug/1529812
[3] https://blueprints.launchpad.net/dragonflow/+spec/sync-neutron-df-db
