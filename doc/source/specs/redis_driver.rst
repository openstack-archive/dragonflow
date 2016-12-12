..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=================
Redis Driver Spec
=================

Include the URL of your launchpad RFE:
https://blueprints.launchpad.net/dragonflow/+spec/driver-of-redis
Add a DataBase support for DragonFlow

Problem Description
===================
Dragonflow will use Publish/Subscribe as a method to realize communication between components.
Redis DB has a good performance of Publish/Subscribe.
So,We need a driver for Redis DB,meanwhile,
if other DB which support Publish/Subscribe only needs overwrite new APIS added here.
dragonflow will have a efficient way to realize communication between different component.

Proposed Change
===============

As dragonflow already has a class for DB API,
here we just need to overwrite those APIs already existed,
and add new APIS for the Publish/Subscribe, based on andymccurdy lib[1].

Populating a Database API
-------------------------
Basic operation for Redis DB,including add/delete/get/modify and so on.
Realization is based on Grokzen lib.
The following diagram shows which components will populate Redis DB Cluster with
driver[4].::

    +------------------+            +----------------+
    |Neutron server    |            |   Redis Driver |
    |                  | func call  |                |
    | Plugins          +----------> |                |
    |                  |            |                |
    |                  |            |                |        +------------------+
    |                  |            |  realize       |        | Redis DB Cluster |
    +------------------+            |  add/del/get   +------> |                  |
                                    |  using DB API  |        |                  |
    +------------------+            |                |        |                  |
    |                  |            |                |        +------------------+
    | Compute Node     | func call  |                |
    |                  +----------> |                |
    | Applications     |            |                |
    |                  |            |                |
    |                  |            |                |
    +------------------+            +----------------+


Publish API
-----------
The new API realizes publish function with channel, based on andymccurdy lib
The following diagram shows how Neutron config changes are published to all local controllers.
It is only a example.::

    +---------------+
    |               |                                          +-----------------+
    |  DF Neutron   |                                          | Redis DB        |
    |  Plugin       |                                          |                 |
    |               |                                          |                 |
    |  Configuration|                                          |                 |
    |  Change       |                                          |                 |
    |               |           call Publish API               |                 |
    |               +----------------------------------------> |                 |
    |               |                                          |                 |
    |               |                                          |                 |
    |               |                                          +-----------------+
    |               |
    +---------------+

Main process of realization:

.. code-block::python

    r = redis.StrictRedis(*args)
    p = r.pubsub()
    r.publish('my-first-channel', 'some data')
    # my-first-channel is channel name,
    # some data is what you want to publish

Special Notice:
'Some data' will be coded into json pattern.
Above example ,subscriber which subscribes the channel'my-first-channel'will receive what
is published.
More details please refer Publish / Subscribe section of [1]

Subscribe API
-------------
If you want to receive message that you publish,you first should do a subscription,if you
do not want to receive message,you should withdraw subscription.
Realization is based on andymccurdy lib.

Here is a example of subscription process:

.. code-block::python

    r = redis.StrictRedis(*args)
    p = r.pubsub()
    p.subscribe('my-first-channel', 'my-second-channel', ...) # my-first-channel is channel name
    p.unsubscribe('my-first-channel') # here unsubscribe the channel


Here is an example of message driver may received:

.. code-block::python

    {'channel': 'my-first-channel', 'data': 'some data', 'pattern': None, 'type': 'message'}

type: One of the following: 'subscribe', 'unsubscribe', 'psubscribe', 'punsubscribe',
                            'message', 'pmessage'.

channel: The channel [un]subscribed to or the channel a message was published to.

pattern: The pattern that matched a published message's channel.
         Will be None in all cases except for 'pmessage' types.
data:
   The message data. With [un]subscribe messages,
   this value will be the number of channels and patterns the connection is currently subscribed to.
   With [p]message messages, this value will be the actual published message.

Special Notice:
This message is only processed by driver.
Message data will be decoded by driver and send into queue.
Psubscribe,Punsubscribe and Pmessage are not used here,they are used for pattern match.[1]

Subscribe Thread For Reading Messages
-------------------------------------
The subscribe thread is in charge of receiving the notifications and sending
them back to the controller. Realization is based on andymccurdy lib.

The subscribe thread loop is depicted in the following diagram::


      +-----------------+                                                   +---------------+
      |                 |                                                   |               |
      |                 |                                                   |   Process     |
      |                 |                       +-----------------+fun call |   Function1   |
      |                 |                       |                 +-------->|               |
      |Subscribe Thread |                       | Message Dispatch|         +---------------+
      |                 |                       |                 |
      | Wait For Message|                       |                 |
      |                 |                       | Read Message    |         +---------------+
      |                 | Send into Queue       | From Queue      |fun call |   Process     |
      | New Message     +----------------------->                 +-------->|   Function2   |
      |                 |                       | Dispatch Message|         |               |
      |                 |                       |                 |         +---------------+
      |                 |                       |                 |
      |                 |                       |                 |
      |                 |                       |                 |         +---------------+
      |                 |                       |                 |fun call |  Process      |
      |                 |                       |                 +--------->  Function3    |
      |                 |                       |                 |         |               |
      +-----------------+                       +-----------------+         |               |
                                                                            +---------------+

Realization Example:

.. code-block::python

    while True:
        for message in p.listen():
            # classify the message channel content, send to different message queue for channel

Special Notice:
Not only three Process Functions.
Driver Subscriber thread is only one thread to do message dispatch according to channel.
listen() is a generator that blocks until a message is available.


Subscriber management
---------------------
This resubscription should be done only when connection to DB server is recovered.

driver only does connection fix,throw exception when connection is recovered,
driver will clear all subscription and user of Subscription do resubscribe.

Connection Setup
----------------
When driver is initialized,it will connect to all db nodes for read/write/get/modify operation.
But for pub/sub, driver will connect to one db node for one pub or one sub.
Driver guarantee connections for pub/sub will be scattered among db nodes.


Exception
---------
First Notice:exception of cluster client and single client are different, need processed separately.
case1:populate db failed
If add operation is failed, driver will delete what you add,
driver will check connection and reconnect if reason is connection lost,
driver will try several times( for example 3), if all trials failed,
driver will return failed, if reason is not connection
problem, driver will also return failed directly. You should return failed to up level,
do not publish, if driver returned failed.

If delete operation is failed, the process is same as above,
except for driver will not rollback delete operation.

case2:publish failed
If this happened,
driver will return failed and check connection also reconnect if reason is connection lost.
If driver return failed, user of API should undo what you done before publish and return failed
to up level

case3:subscribe failed
If this happened,
driver will return failed and check connection also reconnect if reason is connection lost.
If driver return failed, user of api return failed to up level.

case4:subscribe listen exception
If this happened,
Driver will clear all subscription and then try reconnect,
after fix connection then send a message to subscriber, tell that you subscribed is recovered,
subscriber should subscribe again.

References
==========

[1] https://github.com/andymccurdy/redis-py

[2] http://redis.io/commands

[3] https://github.com/Grokzen/redis-py-cluster

[4] http://redis.io/topics/cluster-tutorial
