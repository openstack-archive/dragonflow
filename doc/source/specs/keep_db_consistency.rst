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
As a result, the question becomes how to ganrantee the atomicity of DB
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

The distributed lock is object-based and each object has its own lock in the
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

Code Samples in Core Plugin
---------------------------

When creating a neutron object::

    def create_object(context, obj):
        with db_api.autonested_transaction(context.session):
            obj_db = super(Plugin, self).create_object(context, obj)
        lock_db.create_lock(context, obj_db['id'])
        nb_lock = lock_db.DFDBLock(context, obj_db['id'])
        with nb_lock:
            self.nb_api.create_object(name=obj_db['id'],
                                      topic=obj_db['tenant_id'],
                                      obj_db)

When updating a neutron object::

    def update_object(context, obj):
        obj_id = obj['obj']['id']
        nb_lock = lock_db.DFDBLock(context, obj_id)
        with nb_lock:
            with db_api.autonested_transaction(context.session):
                updated_obj = super(Plugin, self).update_object(context, obj)
            self.nb_api.update_object(name=obj_id,
                                      topic=obj['obj']['tenant_id'],
                                      obj)
        return updated_obj

When deleting a neutron object::

    def delete_object(context, obj_id):
        nb_lock = lock_db.DFDBLock(context, obj_id)
        with nb_lock:
            with db_api.autonested_transaction(context.session):
                updated_obj = super(Plugin, self).delete_object(context,
                                                                obj_id)
            self.nb_api.delete_object(name=obj_id,
                                      topic=obj['obj']['tenant_id'],
                                      obj)
        lock_db.delete_lock(context, obj_db['id'])

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

In the future, the potential options for improvement:

1. For simplicity, we protect the whole API session by distributed lock.
This is definitely not optimal. We can use distributed lock to only protect
NB-API operations and introduce verioned object and synchronization
mechanism [3]. If the versions in Neutron DB and DF DB are not equal,
we sync the object from Neutron DB to DF DB to ganrantee the data is
consistent.

2. The SQL-based lock is not optimal solution. If DF DB provides
atomic operations on a set of read/write operations, we can refactor
the current SQL-based implementation.

3. Remove Neutron DB. As a result, we don't need to bother the consistency
of two distinct databases. We only need to make sure a set of read/write
operations of DF DB is atomic to prevent from race due to concurrency.

References
==========

[1] https://bugs.launchpad.net/dragonflow/+bug/1529326
[2] https://bugs.launchpad.net/dragonflow/+bug/1529812
[3] https://blueprints.launchpad.net/dragonflow/+spec/sync-neutron-df-db 
