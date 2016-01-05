..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==============================
Publish Subscribe Abstraction
==============================

https://blueprints.launchpad.net/dragonflow/+spec/pubsub-module

This spec describe the design of abstracting the publish-subscribe mechanism
from the DB itself.

Problem Description
===================
Current implementation of Dragonflow rely on the pluggable DB driver
to listen to configuration change events.

The process goes like this:
The local controller first reads the DB and sync all needed configuration
and then wait for changes by calling a specific DB driver API with a
callback method to report the changes back to the controller.

It is then the DB driver responsibility to update the controller with
any configuration change.
If the DB solution doesnt support publish-subscribe mechanism, the local
controller will keep polling the DB and try to find changes by comparing
it to its local cache.

Proposed Change
===============
In order to solve the above problems, and in order to optimize the publish
subscribe process to only sync relevant configuration and topology with
the compute node, we abstract the publish-subscribe mechanism from the DB
driver.

Its important to note that this feature is optionally configured in Dragonflow.
The user can disable it and the behaviour will be the same as its been until
now (the publish-subscribe is managed by the DB driver itself).

If the user will enable the publish subscriber module, the local
controller instead of calling the DB driver wait for changes method will call
our own publish subscriber module.

The specific publish-subscribe module can be changed with other implementations.
In case publish-subscriber module is on, every configuration change will trigger
notification event to the pub-sub module in addition to writing
it to the Dragonflow DB.

The following diagram depicts Dragonflow architecture with the build in
publish-subscribe module:

+--------------------+           +-----------------------+
|                    |           |                       |
|  Dragonflow        |           |   NB API Adapter      |
|  Controller        |           |                       |
|                    |           |                       |
|  +--------------+  |           |  +----------------+   |           +---------------+
|  |              |  |           |  |                |   |           |               |
|  |  SYNC Loop   +---------------> | Fetch DB Data  +-------------> |   DB Driver   |
|  |              |  |           |  |                |   |           |               |
|  |              |  |           |  +----------------+   |           +--------+------+
|  |              |  |           |                       |                    ^
|  |              |  |           |  +-----------------+  |                    |  Wait for changes(callback)
|  | Wait for DB  |  |           |  |                 |  |                    |
|  |   Changes    +---------------> |  If NOT pub-sub +-----------------------+
|  |              |  |           |  |                 |  |
|  |              |  |           |  |                 |  |           +----------------+
|  |              |  |           |  |                 |  |           |                |
|  |              |  |           |  | If pub-sub +-----------------> | Pub-Sub Module |
|  +--------------+  |           |  |                 |  |           |                |
|                    |           |  |                 |  |           +----------------+
|                    |           |  +-----------------+  | wait for
+--------------------+           +-----------------------+  changes (callback)


When the controller is brought up it first tries to sync all the relevant policy
from the DB using the NB API which calls the specific loaded DB driver.

When this process ends, up until now the controller had two options, it would
ask the DB driver if it supported publish subscribe, if not the controller
continue with the sync loop and look for changes.

If the DB driver support publish-subscribe the controller calls a specific
API to the driver to register a callback.
The DB driver is responsible to update any DB change to the callback,
The callback gets table name, action ('create', 'set', 'delete'), the key and value
as parameters.

If the user configured pub-sub, the controller instead of calling the DB driver
API calls Dragonflow pub-sub module with the callback.

The pub-sub module is in charge of dispatching configuration changes (DB changes)
to all the local controllers, it expose a simple API of "subscriber" or "publisher".

The pub-sub module will be pluggable and allow different drivers to be developed as
the pubsub module driver that will implement the interface of the pubsub api
referenced below [2].

Publisher
----------
The NB API class is used both by the dragonflow local controller and the Neutron
plugin.

The following diagram shows how DB changes are dispatched to the pub-sub
module and published to all local controllers.

+---------------+        +-----------------+
| DF Neutron    |        |  NB API         |
| Plugin        |        |                 |
|               |        |                 |       +--------------+
|               |        |  Update DF      |       |              |
| Configuration +------> |  DB             +------>+  DB Driver   |
| Change        |        |                 |       |              |
|               |        |                 |       +--------------+
+---------------+        |                 |
                         |                 |
                         |  if pub-sub:    |       +--------------+
                         |    send_event   +-----> |              |
                         |                 |       | Pub-Sub      |
                         |                 |       |              |
                         |                 |       +--------------+
                         |                 |
                         +-----------------+

Its important to note that every controller is also a publisher, as
they register their "chassis name" to the DB and need to notify the
other controllers of the new compute node.
The neutron Server Plugin and The controller will have different port numbers to cover
the use case of all in one deployment

cfg.df.neutron_server_publisher_port
cfg.df.controller_publisher_port

The event will be written into a queue, it will be a multi process queue in the case of
the neutron server that can run on multiple hosts. In the case of the controller
(single process) will be a regular queue. The publisher Thread will read the events
from the queue and publish them to all the subscribers.

              send events Queue

               +-+-+-+-+-+            +---------+
Send_event+--> | | | | | | +--------> |Publisher|  Publish on publish port
               | | | | | |            |Thread   |---------->
               +-+-+-+-+-+            +---------+

**df-db** CLI tool also needs to be enhanced to support publish-subscribe
notifications as it can be used to bind ports to specific compute nodes


Subscriber
----------
The subscriber API is being called by the local controllers, they call
the daemonize() API of the subscriber and send the callback method.

The subscriber is in charge off receiving the notifications from both publishers types
neutron servers and from the other local controllers and sending them for processing.

Its important to note, as mentioned above, that every controller also publish
itself (send details about the compute node like IP, hostname and tunneling protocol)
to the other controllers.
This is done one time on controller bring up, and only if the controller
didn't publish its self before (if a DB entry exists or not in the
chassis table)

The subscriber thread loop is depicted in the following diagram:

+---------------+
|               |                                          +-----------------+
|  Subscriber   |                                          |                 |
|  Thread       |                                          |  DF Controller  |
|               |                                          |                 |
|  Wait for     |                                          |                 |
|  event        |                      DB Changes Queue    |                 |
|               | callback         +--+--+--+--+--+--+     |                 |
|  New event    +----------------> |  |  |  |  |  |  |     |  Read and apply |
|               |                  |  |  |  |  |  |  +---> |  changes        |
|               |                  |  |  |  |  |  |  |     |                 |
|               |                  +--+--+--+--+--+--+     +-----------------+
|               |
+---------------+

The mechanism in which to implement the publisher and subscriber is
totally abstracted from Dragonflow and can later be changed and
optimized.

The default implementation will use zmq queue [1], other driver
could be easily integrated by implementing the interface [2]

DB drivers that don`t support publish-subscribe can leverage this module but
also other DBs that need optimized behaviour.

Reliable Delivery
-----------------
We pubsub module must comply to the following requirements
- Local Cache Consistency
- Recognize losing an event
- Recognize connection drop
- Configurable max time for detecting lost messages

Neutron Publisher Proposed Solution
-------------------------------------
- Local Cache Consistency
We will use trigger based pub sub event without the value, the value
will be fetched using the DB get. This insure consistency and message
ordering in cost of extra latency i.e get.

- Recognize losing an event from the Neutron Server Publishers

Most pub sub implementation and, most specifically zmq, the publisher has no
knowledge of all its connected
subscriber and can not guarantee message delivery. It is like "multicast"
traffic that subscriber are registered on router/switch and do not forward
the subscription to the server.
We need to develop an application layer on top of the pub/sub that guarantee
delivery but as we stated befor do not guarantee order.

We propose to use per publisher a next message ID sequence
,each Neutron server Host will have a single publisher.
Each Publisher will add to the message it's uuid and the next message_id.
Subscriber will sync with all the publisher upon connection on their next id.
The subscribers will make sure they receive the next message in a time
window defined by configuration but will not enforce ordering.
If subscriber did not receive message in the time window defined he will
perform a full sync.
TODO(gampel) Add asequence diagram

- Recognize connection drop
Connection drop from the Subscriber side:

We will connect again and perform a full sync of the local cache

Connection drop from the Publisher side (server crash):

publisher will send a sync up message and in case of inconsistency will send 'sync' action 
that will enforce a full sync on all the local controllers.

- Configurable max time for detecting lost messages
In order to not be dependent on the next event time to detect losing a
message we need a Out-of-band mechanism to query the publisher current next
message id.

Solution 1
----------------
Heartbeat messages from the publishers

Solution 2
----------------
Add a new table in the DF DB with the publishers ID and next message

Solution 3
----------------
Zmq Socket pair connection from the subscribers to the publisher.

Local Controller Publisher Proposed Solution
--------------------------------------------
Local controller published message only on the first time the host is bounded
to the system and registered as a chassis.
For this reason we propose a much simpler solution for the Controller
publishers.
We will send the add chassis message few times to make sure that all the
controllers received it and if necessary use a pull slow path mechanism on the
chassis table

References
==========
[1] http://zeromq.org/
[2] https://review.openstack.org/#/c/263322/20/dragonflow/db/pub_sub_api.py
