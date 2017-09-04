..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

======================================
Database Migration and Rolling Upgrade
======================================

https://bugs.launchpad.net/dragonflow/+bug/1644111
https://bugs.launchpad.net/dragonflow/+bug/1712586

This blueprint describe how to implement upgrades in Dragonflow, including:

* Rolling upgrades, i.e. continuously upgrading the cloud host by host, without
  the need to reinstall

* Database migration, i.e. how to modify the database and upgrade the schema in
  a way that facilitates the above.

Problem Description
===================

Suppose you have a cloud already deployed. You have several controller nodes,
and some compute nodes. You want to upgrade the cloud, but in order to minimize
risk, you only want to upgrade some of the hosts first.

The most difficult part of an upgrade is API and database changes. In
Dragonflow, the API is inferred from the database. Therefore, database
changes become the centre of the upgrade scenario.

This spec proposes a solution on how to upgrade a deployed cloud, without
breaking functionality, including incompatible database upgrades.

Proposed Change
===============

Option 1
--------

Every database object will have a _version_.

Every Dragonflow deployment will support a specific _version_, and older, up
to say, 2 cycle.

Our code will 'prefer' to work on the newest version it knows. If the version
is older, _migration_ code will upgrade the object to the latest version.

Once all Dragonflow services have been upgraded (local controllers, Neutron
plugins, publisher, BGP, etc.), the database can be upgraded using the same
_migration_ code.

In order to support new features, the database modification must be
backwards compatible. This means the schema may only be changed to *add*
models and fields. Removing fields remains possible, but if a new feature
depends on it, it will only be availbale when the entire cloud is upgraded.

In order to support out-of-tree features, the object _version_ will be on
a per-object basis. Migration scripts will note the models they upgrade.

A table will record the latest version of each object.

Pros:
~~~~~

* No modification to non-upgraded services

* Same upgrade code for database upgrade and on-the-fly upgrade

Cons:
~~~~~

* Neutron plugins will either have to know to write both versions, or be
  upgraded last, or provide database object _downgrade_ code.

  This can be worked around by requiring both upgrade and downgrade code, and
  automatically calling the _downgrade_ code when writing an object. Tests can
  verify that _upgrade_ o _downgrade_ = _downgread_ o _upgrade_ = Id.

Option 2
--------

Every database object will have a _version_.

Every Dragonflow deployment will support the lastest database version.

Upgrade will be done to the Neutron API first. And then to the additional
services.

If the NB API reads a database object which is too new, this object will have
to be _downgraded_.

An external service, either using an API call or a library, will receive the
object, its current version and destination version, and convert the versions.

In order to support out-of-tree features, the object _version_ will be on
a per-object basis. Migration scripts will note the models they upgrade.

Pros:
~~~~~

* No need to know latest wanted version when writing the object. Downgrading
  is done in a unified location.

* No need to support older database versions - although may conflict if writing
  is done via a non-upgraded compute host (e.g. a status)

Cons:
~~~~~

* Code modification on non-upgraded elements

References
==========
