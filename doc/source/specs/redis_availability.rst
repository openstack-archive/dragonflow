..
 This work is licensed under a Creative Commons Attribution 3.0 Unsuported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==================
Redis Availability
==================

This spec describe the design of availability of Redis of DragonFlow.

Problem Description
===================

Dragonflow's Redis driver read the Redis cluster topology and cache it
locally in Redis driver's initialization and then it connects to the Redis
master nodes to operate read/write/pub/sub commands.
This cluster topology maybe changed and then start HA in some scenario like
db master node restarting and Dragonflow should detect it that it could
move the connections from the old master node to the new one.

There are two scenarios in Redis cluster topology changing:

1. The connection will be lost when master node restarting.
2. The connection will not be lost while master node changed to slave
   without restarting as using "CLUSTER FAILOVER" command.
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
===============

Description to step 1
---------------------
If this step is done in each controller, there may have too many
Dragonflow compute nodes read the DB cluster in the same time and
redis cluster could hardly handle it.
So create a detecting thread in NB plugin to read the DB topology information
periodically when Neutron server starting and then send the information
to all Dragonflow controllers to check if the DB cluster nodes changed.
And controllers should subscribe a "HA" topic to receive messages from
plugin.
In Dragonflow controller, it never read nodes information from Redis cluster
after initialization but only listen the messages from detecting task from plugin.

There are 2 types of connections between Redis client and cluster:
1. read/write connection, client connects to every Redis master nodes.
2. pub/sub connection, client connects to one of the cluster nodes by hash.

For type 2 connection failure, it should hash to other node immediately.
For type 1 connection failure, it will be updated after receiving messages sent
by detecting task.
Either connection error or MOVED error detected in Redis driver refers to
cluster topology maybe changed.

Note that there will be a reconnection after connection error and
if the reconnection failed too, it means that a HA occurred.

Description to step 2
---------------------
After receiving the cluster information from plugin, local controller will
compare the new nodes with the old nodes and update the topology information
and connections,
then a "dbrestart" message will be sent to db consist module.

The following diagram shows the procedure of Dragonflow:

::

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
==========
[1] http://redis.io/topics/cluster-tutorial

[2] http://redis.io/topics/cluster-spec
