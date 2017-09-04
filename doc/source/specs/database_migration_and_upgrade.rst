..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

======================================
Database Migration and Rolling Upgrade
======================================

https://bugs.launchpad.net/dragonflow/+bug/1644111
https://bugs.launchpad.net/dragonflow/+bug/1712586

Currently, upgrading Dragonflow is not supported. To upgrade Dragonflow, the
new version must be installed on all cloud servers (compute nodes and
controller nodes), and the database must be replaced.

Unless otherwise specified, none of the items below exist prior to this
feature.

This blueprint describe how to implement upgrades in Dragonflow, including:

* Database migration, i.e. how to modify the database and upgrade the schema in
  a way that facilitates the above.

* Cloud upgrades, i.e. upgrading all the servers in the cloud simultaneously.

The following is out of scope, and will be solved under a different feature:

* Rolling upgrades, i.e. continuously upgrading the cloud host by host, without
  the need to reinstall


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

Assumptions:

* DHCP, metadata service, or anything requiring the controller may stop working

* Network modification may not work

* Networking between ports should continue to work normally. Especially l2, l3,
  and security groups.

* Rollback is supported without loss of data before Neutron/Nova writes are
  re-enabled.

Proposed Change
===============

In this spec., we discuss a whole-cloud upgrade. The operator will initiate and
manage it (to make it easier, some tooling can be developed). The upgrade will
be done as follows:

* Neutron writes are disabled

* All Dragonflow processes, Neutron processes, and Dragonflow drivers are
  stopped and upgraded on all nodes.

* Database migration happens. The migration will run from a single machine.

* All stopped services are started on all compute nodes.

* Neutron writes are re-enabled

Database Migration
------------------

Database migration process will perform the following:

* Locate all avaliable migrations in the stevedore managed paths
* Locate all applied migrations from the north-bound database
* Decide whether any migrations should be applied and stop otherwise.
* Take in-memory snapshot of the north-bound database.
* Iterate migrations ordered by their proposed date, and apply each one on the
  in-memory copy of the database.

 * If an error occured, report and stop (nothing was written to the database).
 * If no errors occur, an entry is added to the migration table, specifying the
   migration performed and the current date & time.
* Once all migrations completed, copy in-memory database over actual database.

Each migration will be in a form of a function that acts on the NB API object:

.. code:: python

  def migration(nb_api):
      # For each lport:
      #     Alter some field
      #     Persist in th passed NB API
      pass

From that point on, whenever a patch modifies a database model, a migration
script must be added, unless the upgrade can be done automatically.

Upgrade can be done automatically only in the following cases:

* A field is added, with a default value
* A model is added

Note that deleting a field or model does not happen automatically. This is
because it is assumed the stored information has to be moved somewhere first.

References
==========
