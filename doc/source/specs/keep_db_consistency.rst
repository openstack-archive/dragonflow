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
problem which may happen in the communication among above three types of
data stores.


Problem Description
===================

Currently, Dragonflow architecture has three types of data stores. One is
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

::

    with transaction of Neutron DB:
        call Neutron DB API
    call Dragonflow DB API

When an exception is thrown from Dragonflow DB API, however, Neutron DB
transaction is committed. We need to call re-sync to make sure the two DB is
in the same state. This phenomenon is discovered when Dragonflow is
disconnected after Neutron DB transaction is committed.

* Scenario 2, in Bug [2]:

::

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

::

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

::

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

::

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

When Neutron plugin receives a creation object(router/network/subnet/port, etc)
invoke:

::

    Start Neutron DB transaction for creation operations.
        with session.begin(subtransactions=True):
            Do Neutron DB operations.
        try:
            Do DF DB operations.
            Emit messages via PUB/SUB.
        except:
            rollback Neutron DB operations.
            raise creation exception.

* After Neutron plugin commit the creation operation to Neutron DB
  successfully, if there happened some exceptions in DF DB operations or
  PUB/SUB process, Neutron plugin should rollback the previous commit, and
  raise a creation exception.

When Neutron plugin receives a update/delete object(router/network/subnet/port,
etc) invoke:

::

    Start Neutron DB transaction for DB operations.
        with session.begin(subtransactions=True):
            Do Neutron DB operations.
        try:
            Do DF DB operations.
            Emit messages via PUB/SUB.
        except:
            raise update/delete exception.

* The difference between update/delete invoke and creation invoke is there is
  no need to rollback when catch exception in DF DB operations, for instance,
  it is impossible and unnecessary to rollback all the Neutron DB data for a
  deleted VM, and we can deal with the dirty data in DF DB by other methods.

When DB driver and pub/sub driver find the read/write connection between
Neutron plugin and DF DB, and also the pub/sub connection between Neutron
plugin and pub/sub system are recovered, the driver should notify Neutron
plugin a recover message, Neutron plugin should process the message:

::

    Start handle the recover message:
        pull data from DF DB.
        pull data from Neutron DB.
        do compare with two data set.
        if found object create/update/delete :
            do DF DB operations.
            Emit messages via PUB/SUB.

* During the db comparison, plugin will iterate each object in the two DB,
  if an object in Neutron DB could not be found in DF DB, the object should be
  considered create, if an object in DF DB could not be found in Neutron DB,
  the object should be considered delete, while if an object exists in both DF
  DB and Neutron DB, but the object version is different, the object should be
  considered update, if the version is same, the object should be considered
  same and pass it.

As we know, during the data pulling and comparison period, both of the two
DB data is changing dynamically, for example, a new port data has been written
into Neutron DB, the db comparison thread read the port data from both Neutron
DB and DF DB before the port data is written into DF DB, so the port will be
consider create, in factor, the port data will be written into DF DB soon,
another case, if we find an update port in Neutron DB than DF DB during data
comparison, then the port may be updated again, if the latter update
operation is happened earlier than the former update operation, the new port
data will be covered by the old port data in DF DB, so we start a green thread
to do the data comparison between Neutron DB and DF DB periodically which
introduce a verification mechanism in Neutron plugin, if we found the
performance bottleneck for Neutron plugin, we could consider the 3rd-party
software (such as an additional process or system OM tools) to do this.

As to the verification mechanism for the db comparison, We can mark
and cache the create/update/delete status for each object at the first time
db comparison, and after the second time db comparison, if the status of one
object is still unchanged, so we can confirm the create/update/delete status
and try to do the corresponding operations, but if the status is changed, we
should flush the status for the object by the latest status and then wait for
next db comparison. So we need two times of db comparison to confirm the
status of object.

During the corresponding operations after confirm the object status, it should
try to get the distribute lock, after getting the lock:

    1. If the status is create, it should try to read the object from DF DB,
       if the object is still not exist, we should create this object to DF DB,
       while if the object is exist in DF DB because the object maybe updated
       during the db comparison, so we consider it is not a creating object any
       more and delete the status of this object from cache.

    2. If the status is update, it should try to read the object from DF DB,
       if the object is not exist because the object maybe deleted during the
       db comparison or the object is exist but the object is changed because
       it maybe updated during the db comparison, so we should delete the
       status of this object from cache, otherwise, we should update this
       object to DF DB.

    3. If the status is delete, we could delete this object from DF DB
       directly.

After the above processing is done, the lock will be released.

::

    Start db comparison periodically:
        pull data from DF DB.
        pull data from Neutron DB.
        do compare with object version.
        if found object create/update/delete :
            verification the object.
            if confirmed object status:
                try:
                    db_lock = lock_db.DBLock(context.tenant_id)
                    with db_lock:
                        read and check object from DF DB.
                        if everything confirmed:
                            do DF DB operations.

                        delete object from cache.
                except:
                    raise exception.
            else:
                refresh object status in cache.

Master Neutron Plugin election
------------------------------

We could use the distribute lock mechanism discussed above for the election.
We should define a primary key for the Neutron plugin election in the
distribute lock table, and we should store one data record for each Neutron
plugin in DF DB, the record should be like this, the total_number property
will only be contained in master plugin record:

.. csv-table::
    :header: Attribute,Type,Description

    plugin_name, String, primary key
    role, String, master or normal
    status, String, active or down
    hash_factor, int, used to LB
    total_number, int, total active plugin number
    plugin_time, DateTime, the latest update DateTime

The election process should be like this:

::

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

* Each Neutron plugin will update its own data record in DF DB and detect
  the current master data record which describe the info of master plugin
  periodically. If normal plugin found master plugin break down, it will update
  its own data record to become new master plugin and change the old master to
  normal and set status to down. Also master Neutron plugin should detect
  other plugins to confirm they are alive periodically.

* If a Neutron plugin has got the db-lock, but it is crashed, the db-lock may
  not be released, so each Neutron plugin should check the created-time in the
  db-lock and if it found the db-lock is timeout, it could own the db-lock
  instead of the crashed Neutron plugin.

DB Check Load Balance
---------------------

In multi nodes environment, we should consider Neutron plugin load balance to
do the db comparison work, it can make the work more effective and avoid single
node bottleneck.

Master Neutron plugin will assign hash factor for each existing active plugin
and store the assign result into DF DB. For example, if there are three
active plugins (include master plugin) A, B and C, master plugin could
assign hash factor 0 to A, 1 to B, 2 to C, if a new plugin D join, master
should assign hash factor 3 to D, then if plugin B break down, master plugin
will reassign hash factor 0 to A, 1 to C, 2 to D, plugin will calculate hash
value by object_uuid for each object and get the corresponding result by
using the hash value to mod the total active plugin number, if the result
is equal to the hash factor of the plugin, the object will be processed,
otherwise the object will be passed.

Local Controller Data Sync
--------------------------

* When initialize or restart the local controller, ovsdb monitor module will
  notify all the existing local VM ports, and local controller will fetch the
  corresponding data according to the tenants that these VMs belong to from
  DF DB.

* When DB driver and pub/sub driver find the read/write connection between
  local controller and DF DB, and also the pub/sub connection between local
  controller and pub/sub system are recovered, the driver should notify local
  controller a recover message, local controller process the recover message:

::

    Start handle the recover message:
        get tenant list according to local VM ports.
        pull data from DF DB according to tenant list.
        compare data between local cache and the got data.
        if found object create/update/delete :
            notify to local apps.

When local controller receives the notification message from pub/sub system,
it will compare the version id between the message and the corresponding
object stored in the cache, if version id in the notification is newer, we
will do the update process, otherwise, we will ignore it.

We should start a green thread to do the data comparison between
local controller cache and DF DB periodically by using the similar
verification mechanism as Neutron plugin.

Comparison By Version ID
------------------------

We add the version_id value for every object, it will be generated when
object is created and updated when the object is updated. We will add an
additional table in Neutron DB to store the version info for each object:

.. csv-table::
    :header: Attribute,Type,Description

    obj_uuid, String, primary key
    version_id, String, object version id

Also we will add a version_id attribute into each object in DF DB, when we
create/update an object, we should do like this:

::

    Start create an object:
        db_lock = lock_db.DBLock(context.tenant_id)
        with db_lock:
            create object into Neutron DB.
            generate and write version id into Neutron DB.
            create object into DF DB with version_id

    Start update an object:
        db_lock = lock_db.DBLock(context.tenant_id)
        with db_lock:
            update object into Neutron DB.
            compare and swap version id into Neutron DB.
            update object into DF DB with version_id

After add the version_id into object, we could judge whether the object has
been updated just according to the version_id which makes the db comparison
more effective.

Data sync for ML2 compatibility
-------------------------------

If we want to reuse ML2 core plugin, we should develop Dragonflow mechanism
driver for it, the driver should implement db operations for DF DB and pub/sub
operations, we should also put the db consistency logic into the driver.

For db operations, our Dragonflow mechanism driver should implement
object_precommit and object_postcommit method, the object_precommit method
should not block the main process and could make the Neutron DB transaction
to rollback when it happens exception in the transaction. For object creation,
object_postcommit method should raise a MechanismDriverError if it happens
exception to make Ml2 plugin to delete the resource. For object update/delete,
object_postcommit method could ignore its internal exception because ML2 do
not concern about it in current implementation.

We should add these db consistency functions into our Dragonflow
mechanism driver:

    1. handle discover message.
    2. DB comparison periodically.
    3. Master Neutron plugin election.
    4. multi Neutron plugins load balance.

Work Items
==========

1. Introduce alembic for DB migration. (DONE)
2. Create DB schema for distributed lock. (DONE)
3. Implement distributed lock. (DONE)
4. Protect all the API operations by distributed lock. (DONE)
5. Data sync for ML2 compatibility (DONE)
6. Comparison By Version ID (DONE)
7. SQL-based compare-and-swap operation (DONE)

Potential Improvements
======================

1. For simplicity, we protect the whole API session by distributed lock.
   This is definitely not optimal. We can use distributed lock to only protect
   NB-API operations and introduce versioned object and synchronization
   mechanism [4]. If the versions in Neutron DB and DF DB are not equal,
   we sync the object from Neutron DB to DF DB to guarantee the data is
   consistent.

2. The SQL-based lock is not optimal solution. If DF DB provides
   atomic operations on a set of read/write operations, we can refactor
   the current SQL-based implementation.

3. REMOVE Neutron DB. As a result, we don't need to bother the consistency
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
