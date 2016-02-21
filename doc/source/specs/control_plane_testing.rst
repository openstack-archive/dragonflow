..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=============================
Dragonflow control plane test
=============================

This test plan consists of the following sections:
1. NoSQL Database Test Plan
2. Message Queue Test Plan
3. Neutron Objects Set-Up Time
4. Stress Tests


1. NoSQL Database Test Plan
===========================

Dragonflow can work with a number of NoSQL databases.
Each one has it's own advantages and disadvantages.

Dragonflow supports the following key/value databases:

1. Etcd
2. Redis
3. Ramcloud
4. Zookeeper
5. OvsDB

Some of the databases above support clustering. We will perform tests against
database server configured in single and multiple node.

The system will be tested against the following configuration:

1. All in one server together with NoSQL server
2. Two or more servers required to enable NoSQL clustering configuration.

Some of the results will be compared with MySQL.

First test: random access test scenario
=======================================

The test will create 1000 database objects and performs random access test.
The test will be performed againstt all supported databases and compared with MySQL.
This tests will mimic the case when Dragonflow received a notification when an
object is created and it needs to load object records from the database.

1. Preparation
--------------
The script will create 1000 database objects like routers.

TODO: Create a script here

2. Random access script
-----------------------
The test will fetch a list of all objects from the database and fetch object in
random way. The script will be tested against all supported databases.

TODO: create a script here

3. Record DB process activity
-----------------------------

TODO: Create a script that records db process activity

3. Generate report
------------------

Generate comparison table.


2. Message Queue Test Plan
==========================
Message queue test plan is intended to test Dragonflow PUB/SUB mechanizm.
This test measures the aggregate throughput of a MQ layer.
Currently Dragonflow support only ZeroMQ messaging system.

TODO: Wait till we have more than 1 queue systems to perform test of this sybsystem.
The set-up time test will cover the whole time for object creation including time to
distribute messages for now.


3. Neutron Objects Set-Up Time
==============================

The idea in this test is to measure time for the whole object creation: from calling
Neutron API until OpenFlows rules are changed. In new Dragonflow architecture the
object creation is propagated using the following manner:

1. Neutron receives an API call to create an object (network, subnet, port, etc...)
2. Neutron fires Dragonflow plugin with just created object
3. Dragonflow plugin saves a new record to NoSQL db
4. Dragonflow sends a message with the new object id using the ZeroMQ message
5. Neutron controller receives a message from ZeroMQ with an object id
6. Neutron controller fetches full object records from NoSQL db
7. Neutron controller, if required, creates new nessesary OpenFlow rules.

Now a new object is basically transfered to the actuall OpenFlow rules.

This test will measure time required to perform the whole operation.
In addition to calculating of time requiered to perform one object creation,
we will calculate time for simultaneous creation of multiple objects.

We will calculate time to create multiple objects as listed in the following table:

1. 1 object created
2. 5 objects created
3. 10 objects created
4. 20 objects created
5. 50 objects created
6. 100 objects created
7. 200 objects created

It is important to see that the time required to add new object is growing
linearly.

The results should be saved.

Now we will be able to perfom regression tests and compare results with
new and old Dragonflow versions. In addition, we can run similar tests
against the Neutron OVN deployment and compare results with the Neutron
Dragonflow deployment.


References
==========

[1] http://docs-draft.openstack.org/04/270204/4/check/gate-performance-docs-docs/9264b70/doc/build/html/test_plans/db/plan.html
