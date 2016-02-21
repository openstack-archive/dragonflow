..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=============================
Dragonflow control plane test
=============================

This test plan consists of the following sections:
1. NoSQL Database Test Plan
2. Message Publish Subscribe Test Plan
3. Neutron Objects Set-Up Time
4. Stress Tests

Out of scope:
-------------
1. Evaluation of network throughput in case the system has hundreds of security rules.
We check only time required to deploy these rules in this project.

Our goals:
----------
In this project we would like to see that the time required to add new configuration
element to the system will not exceed XXX Miliseconds and it is write for 99% of the
cases.


1. NoSQL Database Test Plan
===========================

Dragonflow can work with a number of NoSQL databases.
Each one has it's own advantages and disadvantages.

At the time of writing this document, Dragonflow supports the following
key/value databases:

1. Etcd
2. Redis
3. Ramcloud
4. Zookeeper

Some of the databases above support clustering. We will perform tests against
database server configured in single and multiple node.

The system will be tested against the following configuration:

1. All in one server together with NoSQL server
2. Two or more servers required to enable NoSQL clustering configuration.

Some of the results will be compared with MySQL. See bellow.

First test: random access test scenario
=======================================

The test will create 1000 database objects and performs random access test.
We can optionally compare the results agains MySQL by reading values from Neutron DB.
These tests will mimic the case when Dragonflow received a notification when an
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


2. Message Publish Subscribe Test Plan
======================================
Message publish/subscribe test plan is intended to test Dragonflow PUB/SUB mechanizm.
This test measures the aggregate throughput of a MQ layer.
Currently Dragonflow support only ZeroMQ messaging system.

TODO: This test will be done when we will have more than one supported PUB/SUB method.
For now, as an alternative, the set-up time test will cover the whole time for object
creation including time to distribute messages for now.


3. Neutron Objects Set-Up Time
==============================

The idea in this test is to measure time for the whole object creation: from calling
Neutron API until OpenFlows rules are changed. In new Dragonflow architecture the
object when created is propagated using the following manner:

1. Neutron receives an API call to create an object (network, subnet, port, etc...)
2. Neutron calls Dragonflow plugin with just created object
3. Dragonflow plugin saves a new record to NoSQL db
4. Dragonflow sends a message with the new object id using the ZeroMQ message
5. Neutron controller receives a message from ZeroMQ with an object id
6. Neutron controller fetches full object records from NoSQL db
7. Neutron controller, if required, creates new nessesary OpenFlow rules.

Now a new object is basically transfered to the actuall OpenFlow rules.

This test will measure time required to perform the whole operation.
In addition to calculating of time requiered to perform one object creation,
we will calculate time for simultaneous creation of multiple objects.

Object above refferes to the following
--------------------------------------
1. Network
2. Subnetwork
3. Router
4. Security rules
5. Security groups
6. Network ports
7. Floating ips

Basic test at zero state
------------------------
We will calculate time to create multiple objects when system is at zero state.
We define zero state as a state where we have a system with default rules only.
We will do the following tests:

1. 1 object created
2. 5 objects created
3. 10 objects created
4. 20 objects created
5. 50 objects created
6. 100 objects created
7. 200 objects created
8. 500 objects created
9. 1000 object created


Multiple tenants
----------------
As Dragonflow addresses different tenants as different pub/sub channels,
notification on object created in forwarded to one of another channel.
So, the results, when using one tenant and multiple tennants will be
different.

Heavy usage of the system (at single box)
-----------------------------------------
In this test we will pre-create a lot of objects in the system and then we will
measure time to add a new object to the system that is actively used.

What we are going to test
-------------------------
1. Check that objects are created are valid and correct Openflow rules are created
1. We will measure time to create one or group of objects
2. We will measure CPU usage


Now we will be able to perfom regression tests and compare results with
new and old Dragonflow versions. In addition, we can run similar tests
against the Neutron OVN deployment and compare results with the Neutron
Dragonflow deployment.


4. Stress Tests Scenarios
=========================
In this test we want to stretch the system to it's maximal capabilities
and calculate time required in different scenarios.

For example we want to see how many small VM's we can launch on a single
box and how much time it takes to deploy all of them. In addition, we want
to check that all of the VMs got an IP address.

Test scenarios for single server installation:
1. 1 Router with 1000 Subnetworks
2. 1000 Routers - 1000 Subnetwork (1 subnetwork in 1 router)
3. 100 Routers - 500 subnets
4. 1000 Security rules for 1 VM
5. 1000 Security rules for 10 VMs
6. Launch 100 VMs
7. Set up 1000 Security rules in 1 Security group
8. Etc...

Transcript from emails:
There is also a control plane performance issue when we try to catch on the spec of typical AWS limit (200 subnets per router). When a router with 200 subnets is scheduled on a new host, a 30s delay is watched when all data plane setup is finished.

More to address:
Create max Subnet on a router or for a tenant test create 1000 SG etc

References
==========

[1] http://docs-draft.openstack.org/04/270204/4/check/gate-performance-docs-docs/9264b70/doc/build/html/test_plans/db/plan.html
[2] http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_Appendix_Limits.html
[3] https://aws.amazon.com/vpc/faqs/
