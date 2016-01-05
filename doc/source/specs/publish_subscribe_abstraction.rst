..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=============================
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

**df-db** CLI tool also needs to be enhanced to support publish-subscribe
notifications as it can be used to bind ports to specific compute nodes


Subscriber
----------
The subscriber API is being called by the local controllers, they call
the daemonize() API of the subscriber and send the callback method.

The subscriber is in charge to receiving the notifications and sending
them back to the controller, similar to the process that a DB driver
would do.

Its important to note, as mentioned above, that every controller also publish
itself (send details about the compute node like IP, hostname and tunneling protocol)
to the other controllers.
This is done one time on controller bring up, and only if the controller
didn't publish its self before (if a DB entry exists or not in the
chassis table)

The following diagram depicts this process:

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

The default implementation will use nanoqueue [1], but it can be easily
changed.

DB drivers that don`t support publish-subscribe can leverage this module but
also other DBs that need optimized behaviour.

References
==========
[1] http://nanomsg.org/
