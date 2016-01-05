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

The flow is as follows:

* The local controller reads the DB and sync all needed configuration
* Then, it waits for change notifications by calling a specific DB driver API with a
  callback method to report the changes

It is then the DB driver responsibility to update the controller with
any configuration change.

If the DB driver doesn't support publish-subscribe mechanism, the local
controller will keep polling the DB and search for changes by comparing
it to its local cache.

This is very inefficient and not very scalable.

Some DB drivers do support publish-subscribe mechanism, but in some cases it
is not reliable and scalable enough.

Proposed Change
===============

We require a consistently reliable and scalable publish-subscribe mechanism.

In order to be efficient with large scale deployments, we want to only sync
relevant configuration and topology with the compute node.

We therefore want to abstract the publish-subscribe mechanism from the DB driver,
so that we can control the publishing topics in an applicative manner.

We require that this change will be *optional* allowing the user to default to
the previous behavior, i.e. the publish-subscribe is managed by the DB driver
itself.

We introduce a pluggable Pub-Sub mechanism driver, in order to allow different
implementations to drive the solution.

In the reference implementation, we will use ZeroMQ (ZMQ).

Solution Overview
-----------------

The Local Dragonflow Controller is the *Subscriber*.

The Neutron Server API is the *Publisher*.

The *Publisher* uses the Pub-Sub API [2] to publish to relevant topics.

The *Subscriber* uses the Pub-Sub API [2] to register to relevant publishers
on relevant topics.

The *Publisher* publish every change from Neutron API to the topic it is
connected to, as a notification event.

The *Subscriber* is triggered by notification events and uses the data to
update the Dragonflow Local Controller.

Interoperability with previous mechanism
----------------------------------------

The following diagram depicts Dragonflow existing DB Driver-based mechanism
interoperability with the proposed built-in publish-subscribe capability:

::

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
continues with the sync loop and look for changes.

If the DB driver support publish-subscribe the controller calls a specific
API to the driver to register a callback.
The DB driver is responsible to update any DB change to the callback,
The callback gets table name, action ('create', 'set', 'delete'), the key and value
as parameters.

If the user configured pub-sub, the controller instead of calling the DB driver
API calls Dragonflow pub-sub module with the callback prior to starting the full sync process.

The pub-sub module is in charge of dispatching configuration changes (DB changes)
to all the local controllers, it expose a simple API of "subscriber" or "publisher".

The pub-sub module will be pluggable and allow different drivers to be developed as
the pubsub module driver that will implement the interface of the pubsub api
referenced below [2].

Publisher
---------
The NB API class is used both by the Dragonflow local controller and the Neutron
plugin.

The following diagram shows how DB changes are dispatched to the pub-sub
module and published to all local controllers.

::

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
 

Neutron Server q-svc process is forked on a multi-core host, in order to work
around Python cooperative threading.

Each q-svc uses an IPC mechanism provided by the Publisher driver, in order
to push its events through a shared
*Publisher Service*, which binds to a one-per-host socket.

::

 +---------------------------------------------------------------+
 |                                                               |
 |  Neutron Server API Host                                      |
 |              +----------+                                     |
 |              |          |                                     |
 |              | q-svc_1  +------------+                        |
 |              |          |            |                        |
 |              +----------+            |                        |
 |                                      |                        |
 |              +----------+            |                        |
 |              |          |            |                        |
 |              | q-svc_2  +----------+ |                        |
 |              |          |          | |   +----------+         |
 |              +----------+          | +--->          |         |
 |                                    +-----> publisher|         |
 |              +----------+          +-----> service  |         |
 |              |          |          | +--->          |         |
 |              | q-svc_3  +----------+ |   +----------+         |
 |              |          |            |                        |
 |              +----------+            |                        |
 |                                      |                        |
 |              +----------+            |                        |
 |              |          |            |                        |
 |              | q-svc_4  +------------+                        |
 |              |          |                                     |
 |              +----------+                                     |
 |                                                               |
 +---------------------------------------------------------------+


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

::

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
We define pub-sub reliability by the following factors:

* Local Cache Consistency
* Recognize losing an event
* Recognize connection drop
* Configurable max time for detecting lost messages

Neutron Publisher Proposed Solution
===================================

Since most pub-sub implementations don't guarantee delivery, we need to build
an applicative method to track message order and verify delivery.

Delivery
--------

In order to detect message delay/loss, we introduce a *per-pub-per-message* sequence ID.
The client verifies the sequence order of messages by tracking *current per-pub-message-id*.

In case the client detects sequence that is >2 IDs from the *current*, it will wait
for a period defined by *message delay window* for the missing messages to arrive. 

If the time elapsed and some messages did not arrive, the client will perform a full sync against the DB.

Flow 1: Subscriber (re)connects 
-------------------------------

When a subscriber connects for the first time, or reconnects after an outage, it will do full-resync.

TODO: We will optimize this in a future release, using a "publisher running life signature".

Flow 2: Publisher (re)connects
------------------------------

When a publisher connects for the first time, or reconnects after an outage,
it will publish its initial sequence number and its UUID, in a special *hello* message.

The subscribers will receive this message and reset their *current per-sub-per-message-id* accordingly.

Flow 3: Subscriber missed a message in a mostly-idle system
-----------------------------------------------------------

When the system is mostly idle, a subscriber may miss a message and not detect it for a long time.

In order to mitigate this, the publisher will emit its *hello* message every configurable *max_idle_time*.

We define Idle Time as a period of time where no messages are published from a specific publisher.

Order
-----

We introduce *versioning* on the object level in the database, in order to track message order.

We compare this versioning to the local cache, before we update it.  

We only update when local cache version is older, and drop updates that have older version than the local cache.

Neutron Server Publisher discovery
==================================

Each subscriber (i.e. Distributed Dragonflow Controller) uses a local configuration with the addresses of the publishers.

TODO: We will optimize this by adding a Service Directory in the Dragonflow database.

Controller-to-Controller Publisher Proposed Solution
====================================================

Local Controllers publish messages through the Neutron Server, by writing to the Dragonflow database.

A polling mechanism in the Dragonflow publisher service detects such updates and publish them to everyone.

This mechanism is enough for handling rarely-occurring events, such as chassis registration (i.e. adding new compute nodes).

TODO: if we will see significant increase in Controller-to-Controller publishing traffic, we will implement an enhancement to 
enable multi-publisher-multi-subscriber mechanism, using something like ZMQ EPGM.

Configuration Options 
======================
'enable_df_pub_sub', default=False, help=_("Enable use of Dragonflow built-in pub/sub")),
'pub_sub_driver', default='zmq_pubsub_driver', help=_('Drivers to use for the Dragonflow pub/sub')),
'publishers_ips', default=['$local_ip'], help=_('List of the Neutron Server Publisher IPs.')),
'publisher_port', default=8866, help=_('Neutron Server Publishers Port'))

References
==========
[1] http://zeromq.org/
[2] https://github.com/openstack/dragonflow/blob/master/dragonflow/db/pub_sub_api.py

pubsub.txt
Displaying pubsub.txt.
