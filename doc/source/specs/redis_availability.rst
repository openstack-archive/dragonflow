..
 This work is licensed under a Creative Commons Attribution 3.0 Unsuported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=============================
Redis Availability
=============================

This spec describe the design of availability of Redis of DragonFlow.

Problem Description
====================

Dragonflow's Redis driver read the Redis cluster topology and cache it
locally in Redis driver’s initialization and then it connects to the Redis
master nodes to operate read/write/pub/sub commands.
This cluster topology maybe changed and then start HA in some scenario like
db master node restarting and Dragonflow should detect it that it could
move the connections from the old master node to the new one.

There are two scenarios in Redis cluster topology changing:
1. The connection will be lost when master node restarting.
2. The connection will not be lost while master node changed to slave
without restarting as using “CLUSTER FAILOVER” command.
In this case one slave will be promoted to master and the client
could not get connection error but a MOVED error from server after
sending request to the new slave node.

Some data maybe lost in Redis HA because Redis does not
provide strong consistency. So for this case,
driver should notify DB Consistency module to resynchronize
local data to Redis cluster after the Redis cluster finishing HA.

The goal of this design is to describe how to
keep available of Redis cluster if node crashing occurred.
It could be divided into 2 steps:
1. Detecting changes of cluster topology
2. Processing HA after detection

Proposed Change
================

Description to step 1
-------------------------------------
Either connection error or MOVED error detected in driver refers to
cluster topology change.
So a notification of HA should be notified.
Note that there will be a reconnection after connection error and
if the reconnection failed too, it means that a HA occurred.

Description to step 2
------------------------
After detecting the node failure,
a new thread will be started to read new Redis cluster
topology information periodically because there is a few seconds
in Redis cluster HA. The thread will be started in NB Plugin.
If the cluster state is ok and
master node status is not fail, the driver will update
the topology information and reset connections,
then the thread stops and a “sync” message will be sent.
If the cluster state is fail or master node status is fail,
the thread will keep reading topology till the Redis cluster
finishing HA and meanwhile read or write requests could not be operated.

The following diagram shows the procedure of Dragonflow:

NB
+-------------------------------+
|         1.notify              |
+--------+------> +----------+  |
||driver |        |DB consist|  |
|--------+        +----------+  |
+-------------------------------+
                    |
       2.resync data|
                    |
+-------------------v------+
|                          |
|                          |
|      Redis cluster       |
|                          |
|                          |
+--------------------+-----+
                     ^
      2.resync data  |
                     |
+-------------------------------+
|         1.notify   |          |
+--------+------> +--+-------+  |
||driver |        |DB consist|  |
|--------+        +----------+  |
+-------------------------------+
SB

References
===========
[1] http://redis.io/topics/cluster-tutorial
[2] http://redis.io/topics/cluster-spec
