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
Neutron DB and Dragonflow DB, also between Dragonflow DB and Dragonflow local
controller cache. As we know, Neutron DB stores the virtualized
network topology of OpenStack clouds. It is a reliable relational data store
and can be considered as the master DB in Dragonflow distributed architecture.
As a result, the question becomes how to guarantee the atomicity of DB
operations across two distinct kinds of database in the one API session.
Here we will propose a simple and feasible distributed lock solution and
improve it later according to evaluation in production. We also provide an
effective data synchronization mechanism to resolve the data inconsistency
problem which may happen in the communication among above three type of
data stores.


Problem Description
===================

Currently, Dragonflow architecture has three type of data stores. One is
Neutron DB responsible for storing virtualized network topology. This database
is relational and all the operations on it are based upon atomic transactions.
It is considered as the master DB of Dragonflow. The other is distributed NoSQL
DB responsible for storing Dragonflow-related topology, the subset of Neutron
DB. It is considered as the slave DB of Dragonflow. Its API, encapsulated by
Dragonflow, lacks of atomic transaction in general which causes inconsistency.
The third is Dragonflow local controller cache which is the subset of
Dragonflow NoSQL DB based on selective topology storage mechanism, it makes
Dragonflow local controller visit its concerned data much faster.

There are several problems related with DB inconsistency in the current
codebase. The pseudo-code or description to demonstrate the inconsistency
is as follows:

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

* Scenario 3:

    1. Dragonflow local controller subscribe its concerned data;
    2. Neutron plugin publish a new created data;
    3. Dragonflow local controller receive data and store in the cache.

After Dragonflow local controller subscribe its concerned data, the sub/pub
connection between local controller and sub/pub system is down because of the
breakdown of network or sub/pub system, so local controller will lose the new
data. Another case is after local controller receives the pub message, it
happens internal exception in the data process, then the new data will be
dropped.

* Scenario 4:

    1. A VM online on a Dragonflow local controller host while it is the first
    VM of one tenant on the host;
    2. The local controller will fetch all the data belong to the tenant from
    Dragonflow NoSQL DB.

After the VM online, the data read/write connection between local controller
and Dragonflow NoSQL DB is down because of the breakdown of network or the
problem of DB itself(restart or node crash), then the local controller will
lose the tenant data it concerned.


Proposed Change
===============

To solve the problems discussed in Scenario 2, the general idea is to
introduce a distributed lock mechanism for core plugin layer. The distributed
lock is to protect the API context and prevent from concurrent write
operations on the same records in the database. As to the problems discussed
in Scenario 1, 3 and 4, we need a effective data synchronization mechanism.

Distributed Lock
----------------

To solve these problems, a SQL-based distributed lock mechanism is introduced.
A carefully-designed SQL transaction is capable of being an external atomic
lock to protect all the dependent database operations both for Neutron DB and
DF distributed NoSQL server in a given API context. This can greatly reduces
the complexity of introducing other sophisticated synchronization mechanism
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
--------------------------

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

Data Synchronization
--------------------

We discussed the Data Synchronization Mechanism from two aspects:

    1. Neutron plugin;
    2. Dragonflow local controller.

Neutron Plugin Data Sync
------------------------

When Neutron plugin receives a creation object(router\network\subnet\port, etc)
invoke:

    Start Neutron DB transaction for creation operations.
        Do Neutron DB operations.
    try:
        Do DF DB operations.
        Emit messages via PUB/SUB.
    except:
        retry to do DF DB operations and PUB/SUB.
        if beyond max retry times:
            rollback Neutron DB operations.
            raise creation exception.

* After Neutron plugin commit the creation operation to Neutron DB
successfully, if there happened some exceptions in DF DB operations or PUB/SUB
process, Neutron plugin should retry several times to finish commits and
PUB/SUB, if it failed after all the attempts, Neutron plugin should rollback
the previous commit, and raise a creation exception.

When Neutron plugin receives a update\delete object(router\network\subnet\port,
etc) invoke:

    Start Neutron DB transaction for DB operations.
        Do Neutron DB operations.
    try:
        Do DF DB operations.
        Emit messages via PUB/SUB.
    except:
        retry to do DF DB operations and PUB/SUB.
        if beyond max retry times:
            raise update\delete exception.

* The difference between update\delete invoke and creation invoke is there is
no need to rollback when beyond max retry times, for instance, it is impossible
and unnecessary is rollback all the Neutron DB data for a deleted VM, and we
can deal with the dirty data in DF DB by other methods.

When DB driver and pub\sub driver find the read\write connection between
Neutron plugin and DF DB, and also the pub\sub connection between Neutron
plugin and pub\sub system are recovered, the driver should notify Neutron
plugin a recover message, Neutron plugin should process the message. As we
know, during the data pulling and comparison period, both of the two DB data
is changing dynamically, for example, if we find an additional port in Neutron
DB than DF DB during data comparison, then the port may be deleted, if
the delete operation is happened earlier than the create operation, the dirty
data of this port will be stored in DF DB, so we introduce a verification
mechanism for the message process.

We can store the create\update\delete status for each object at the first time
db comparison, and after the second time db comparison, if the status of one
object is unchanged, we can confirm the create\update\delete operation and do
the corresponding operations, but if the status is changed, we should flush
the status for the object by the latest status and then wait for next db
comparison.

    Start handle the revcover message:
        pull data from DF DB.
        pull data from Neutron DB.
        do compare with two data set.
        if found object create\update\delete :
            verification the object.
            if confirmed object status:
                try:
                    do DF DB operations.
                    Emit messages via PUB/SUB.
                except:
                    retry to do DF DB operations and PUB/SUB.
                    if beyond max retry times:
                        raise exception.
            else:
                refresh object status.

* Optionally, we could start a green thread to do the data comparison between
Neutron DB and DF DB periodically in Neutron plugin, if we found the
performance bottleneck for Neutron plugin, we could consider the 3rd-part
software (such as an additional process or system OM tools) to do this.

Neutron Plugin election
-----------------------

We could use the distribute lock mechanism discussed above for the election.
We should define a primary key for the Neutron plugin election in the
distribute lock table, then the election should be like this:

    def get_master_neutron_plugin(context):
        nb_lock = lock_db.DBLock(context.election_key)
        with nb_lock:
            if db_api.get_master_plugin_name() == self.plugin_name:
                db_api.set_master_plugin_time(self.current_time)
                return True
            elif self.current_time > master_old_time + timeout:
                db_api.set_master_plugin_time(self.current_time)
                db_api.set_master_plugin_name(self.plugin_name)
                return True
            else:
                return False

* Each Neutron plugin will detect the current master by read and check the
data record in DF DB which describe the info of master plugin periodically,
and when it find the master is itself, it will handle the recover message
as discussed above, else it will do nothing for the message.

* If a Neutron plugin has got the db-lock, but it is crashed, the db-lock may
not be released, so each Neutron plugin should check the created-time in the
db-lock and if it found the db-lock is timeout, it could own the db-lock
instead of the crashed Neutron plugin.

Local Controller Data Sync
--------------------------

* When initialize or restart the local controller, ovsdb monitor module will
notify all the exist local VM ports, and local controller will fetch the
corresponding data according to the tenants that these VMs belong to from
DF DB.

* When DB driver and pub\sub driver find the read\write connection between
local controller and DF DB, and also the pub\sub connection between local
controller and pub\sub system are recovered, the driver should notify local
controller a recover message, local controller should process the message:

    Start handle the recover message:
        add local chassis data to DF DB.
        publish local chassis data.
        get tenant list according to local VM ports.
        pull data from DF DB according to tenant list.
        compare data between local cache and the got data.
        if found object create\update\delete :
            notify to local apps

* Optionally, we could start a green thread to do the data comparison between
local controller cache and DF DB periodically.


Work Items
==========

1. Introduce alembic for DB migration. (DONE)
2. Create DB schema for distributed lock. (DONE)
3. Implement distributed lock. (DONE)
4. Protect all the API operations by distributed lock. (DONE)
5. Data sync for ML2 compatibility (TODO)

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
