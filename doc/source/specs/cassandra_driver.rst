..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=====================
Cassandra Driver Spec
=====================

Include the URL of the launchpad RFE:
https://blueprints.launchpad.net/dragonflow/+spec/cassandra-support

Problem Description
===================

Apache Cassandra [#]_ is a key-value store and widely used in
large-scale real-time internet applications, such as Netflix, Reddit,
The Weather Channel, etc.

.. [#] http://cassandra.apache.org/

The performance is amazing and generally dominates others according
to universities' research reports [#]_.

.. [#] http://www.planetcassandra.org/nosql-performance-benchmarks/

Besides performance, it also has many noticeable advantages such as

#. Fault-tolerant: Data is automatically replicated to multiple nodes
   for fault-tolerance. Replication across multiple data centers is supported.
   Failed nodes can be replaced with no downtime.
#. Decentralized: There are no single points of failure. There are no network
   bottlenecks. Every node in the cluster is identical.
#. Horizontally Scalable: Read and write throughput both increase linearly
   as new machines are added, with no downtime or interruption to applications.
#. Durable: It is suitable for applications that can't afford to lose data,
   even when an entire data center goes down.
#. In Control: Choose between synchronous or asynchronous replication for each
   update. Highly available asynchronous operations are optimized with features
   like Hinted Handoff and Read Repair.
#. Easy to Maintain: The control plane of the whole geographically-distributed
   data cluster is fully implemented without support of external applications.
   It also provides an operation portal for daily maintenance.

Currently, we implement control plane of clustering for Redis inside Dragonflow,
which is actually beyond the scope of Dragonflow project. The reason why we
implement db-api layer is that we do not want to maintain the details of data
backend as it is not the responsibility of Dragonflow project.

The disadvantage of Cassandra is that it needs external mechanism for PUB/SUB,
for example, Zookeeper or ZeroMQ. The latter has been implemented in Dragonflow,
so it is usable for now.

It is noted that Cassandra is run over JVM.

Highlights
----------

In this section I will highlight some internal mechanisms of Cassandra that will
greatly help Dragonflow scale out and put into production.

#. You can adjust ReplicationFactor to have multiple replications across data centers.
#. You can adjust ConsistencyLevel to use different algorithms, like Quorum.
#. Every node in the cluster is identical. No Master or Slave roles.
#. The data written to Cassandra node is going to append-only CommitLog first and
   fsync to disk next. You also can adjust the policy of fsync. It guarantees the durability.

High Availability
-----------------

You just need to specify a set of nodes in configuration, *remote_db_hosts* in [df] section.
The nodes will automatically form a Quorum-like cluster with replications and consistency
you specify in Cassandra configuration.

JVM in Production
-----------------

Although this section is beyond the scope of Dragonflow, the following links are provided
by Cassandra official to guide users on tuning Cassandra and JVM.

#. https://docs.datastax.com/en/landing_page/doc/landing_page/recommendedSettingsLinux.html
#. https://docs.datastax.com/en/cassandra/3.x/cassandra/operations/opsTuneJVM.html

It is observed that the operations on data store in Dragonflow is read intensive according to
monitoring in the production. This is actually not the Dragonflow's characteristic but the
Neutron's. Most of the operations on data store in Neutron are *high concurrent read*.

Here is another link [#]_ that provides hints on how to optimize JVM in Cassandra for
read heavy workloads.

.. [#] http://www.planetcassandra.org/blog/cassandra-tuning-the-jvm-for-read-heavy-workloads/

Proposed Change
===============

#. Implement devstack script for deploying Cassandra.
#. Implement Cassandra driver
#. Implement unit tests

Implementation
==============

Assignee(s)
-----------

Primary assignee:
  `nick-ma-z <https://launchpad.net/~nick-ma-z>`_
