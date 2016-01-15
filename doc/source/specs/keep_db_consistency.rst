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
design, we will first propose several potential solutions and discuss the
pros and cons. Finally, we will conclude which way to go.


Problem Description
===================

Currently, Dragonflow architecture has two type of data stores. One is Neutron
DB responsible for storing virtualized network topology. This database is
relational and all the operations on it are based upon atomic transaction.
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
transaction is committed. We have to set up a rollback mechanism to make sure
the two DB is tied up. This phenomenon is discovered when Dragonflow is
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
lock mechanism for DB-API layer.

The full-sync mechanism is to synchonize all the virtual topology from
Neutron DB to DF distributed NoSQL server when the data is inconsistent.
It runs at the background and checks the consistency periodically.

The distributed lock is to protect the API context and prevent from
concurrent write operations on the same records in the database.

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
        Obtain the distributed lock from Neutron DB.
        Update the distributed lock to DF DB.
        Do Neutron DB operations.
        Release the distributed lock in Neutron DB.
        Do DF DB Operations.
        Emit messages via PUB/SUB.
        Release the distributed lock in DF DB.

* When obtaining the distributed lock, it creates a DB transaction and update
Neutron DB and DF DB in the same transaction to prevent from inconsistency. As
a result, the update operations are both conducted or failed.

Data Model Impact
-----------------

As noted above, the spec adds a new table for the distributed lock in Neutron
DB. A migration script will be provided. The table is designed as follows:

.. csv-table::
    :header: Attribute,Type,Description

    tenant_id, String, primary key
    lock_id, String, lock id generated for a given API session

References
==========

[1] https://bugs.launchpad.net/dragonflow/+bug/1529326
[2] https://bugs.launchpad.net/dragonflow/+bug/1529812
