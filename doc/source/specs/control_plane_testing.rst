..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

Dragonflow control plane test
=============================

The test consists of the following sections:
1. NoSQL Database Test Plan
2. Message Queue Test Plan


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

The test will create 1000 database objects and performs random access.
The test will be performed againstt all supported databases and compared with MySQL.
This tests will mimic the case when Dragonflow received a notification when an
object is changed and it needs to load object records from the database.

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

