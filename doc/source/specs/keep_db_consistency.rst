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
full-sync mechanism for Neutron plugin layer and introduce a virtual
transaction mechanism for DB-API layer.

Full-Sync Mechanism
-------------------

In Neutron plugin:
    When initialize the neutron df plugin:
        Run compare-db to identify the difference between two DBs.
        Run update-df-db to make it be synchronized.

    Run a df-db-health-checker greenthread or external process:
    (this should be an option for df-plugin):
        Periodically run compare-db and call update-df-db if necessary.

If multiple neutron-server starts with full-sync simultaneously, the database
is still in chaos. As a result, the whole database should be locked in advance.
To achieve this, the DB-API layer should provide a global lock mechanism.
The pseudo-code is as follows:

    If df_plugin.db.driver.locked(‘global_key’, ’key’):
        Run compare-db to identify the difference between two DBs.
        Run update-df-db to make it be synchronized.

In DB-API, introduce a global lock function:

    def locked(self, table, key):
        int total_wait_time = 0
        while(self.compare_and_swap(table, key, new_val=1, old_val=0)):
            time.sleep(duration)
            total_wait_time += duration
            if total_wait_time > MAX_LOCKED_TIME:
                raise TimeoutException
        return True

In addition, the DB backend driver should provide a compare-and-swap function
to update the global lock.

Virtual Transaction Mechanism for DB-API
----------------------------------------

The problem is how to implement the virtual transaction for Dragonflow DB
layer. Here I’ll introduce several potential solutions for such a virtual
transaction.

Transaction API in DB-API layer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We implement a set of atomic transaction APIs in DB-API layer. So, we let the
DB driver implement it.

    def NB-API-operation(context, df_context):
        with df_context.virtual_transaction of Dragonflow DB:
            with context.transaction of Neutron DB:
                call Neutron DB API
    		call Dragonflow DB API

Pros:
It simplifies the NB-API layer. The usage of transaction of DB-API is the same
to SQLalchemy.

Cons:
If some DB driver doesn’t have the related atomic operations, the DB driver is
useless for Dragonflow.

The inner transaction increases the possibility of the outer transaction
timeout, which causes the whole operation fails. It also increases the
pressure of maintaining concurrent transactions of relational DB cluster.

Distributed Lock Manager
~~~~~~~~~~~~~~~~~~~~~~~~

We can introduce a general DLM to deal with this problem.

In the virtual transaction:
    def _enter():
        for each (table, key):
            self.dlm.obtain_lock(table, key)
            add (func, table, key, value) into func_list

    def _exit():
        for each func in func_list:
            call func(table, key, value)
            self.dlm.release_lock(table, key)

    def _on_exception():
        for each func in called_func_list:
            call reverse func(table, key, old_value)
            self.dlm.release_lock(table, key)
        re-raise exception

Currently OpenStack has a project aimed to implement DLM, openstack/tooz, which
also implements plug-able DB like what Dragonflow does. It supports Zookeeper,
Redis, etc. However, the exposed interfaces of tooz are designed for
distributed coordination, not DB store. So, we cannot take advantage of tooz
as our DB-API layer and we can only introduce tooz as the DLM in Dragonflow.
As a result, we have two overlapped DB backends.

We also can implement our own DLM dedicated for Dragonflow, which can reuse the
DB backends and simplify the architecture.

In DB-API:
    def obtain_lock(self, session_id, table, key):
        int total_wait_time = 0
        while(self.compare_and_swap(table, key, new_val=session_id, old_val=0)):
            time.sleep(duration)
            total_wait_time += duration
            if total_wait_time > MAX_LOCKED_TIME:
                raise TimeoutException
        return True

    def release_lock(self, session_id, table, key):
        int total_wait_time = 0
        while(self.compare_and_swap(table, key, new_val=0, old_val=session_id)):
            time.sleep(duration)
            total_wait_time += duration
            if total_wait_time > MAX_LOCKED_TIME:
                raise TimeoutException
        return True

Pros:
It can solve it in a unified way, both for full-sync and virtual transaction.

Cons:
You need to work hard on it, because it is a brand-new mechanism introduced to
Dragonflow.

Global ActionQueue
~~~~~~~~~~~~~~~~~~

We implement a global ActionQueue for queuing all the Dragonflow DB operations
for a given Neutron DB transaction. The pseudo-code is as follows:

def NB-API-operation(context, df_context):
    with df_context.virtual_transaction.precommit of Dragonflow DB:
        with context.transaction of Neutron DB:
            call Neutron DB API
            call Dragonflow DB API

    with df_context.virtual_transaction.postcommit of Dragonflow DB:
        pass

In the virtual transaction.precommit:
    def _enter():
        if self.is_parent:
            self.session_id = generate_uuid()
        self.global_queue.enqueue(session_id, list[func, table, key, value])

    def _on_exception():
        if self.is_parent:
            self.global_queue.clean(session_id)
        re-raise exception

In the virtual transaction.postcommit:
    def _enter():
        if self.is_parent:
            func_list = self.global_queue.dequeue(session_id)
            for each func in func_list:
                call func(table, key, value)

    def _on_exception():
        if self.is_parent:
            for each func in called_func_list:
            call reverse func(table, key, old_value)
            re-raise exception

The global ActionQueue should be implemented as an external service, such as
Neutron DB or the existing Dragonflow DB backends. No matter what we use as the
ActionQueue, the backend should provide a general transaction mechanism.

Pros: 
The implementation is easy to achieve and understand.

Cons:
The global DB service which stores the ActionQueue is the performance
bottleneck of control plane. Deploying in large-scale, the concurrent read and
write operations on the global ActionQueue could be considered as the DoS.
It will affect scalability of the Dragonflow architecture.

Conclusion
----------

In discussion.

References
==========

[1] https://bugs.launchpad.net/dragonflow/+bug/1529326
[2] https://bugs.launchpad.net/dragonflow/+bug/1529812
