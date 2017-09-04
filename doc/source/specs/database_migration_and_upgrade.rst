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

This blueprint describes how to implement upgrades in Dragonflow, including:

* Database migration, i.e. how to modify the database and upgrade the schema in
  a way that facilitates the above.

* Cloud upgrades, i.e. upgrading all the servers in the cloud simultaneously.

The following is out of scope, and will be solved under a different feature:

* Rolling upgrades, i.e. continuously upgrading the cloud host by host, without
  the need to stop the entire control plane for upgrade.


Problem Description
===================

Suppose you have a cloud already deployed. You have several controller nodes,
and some compute nodes. You want to upgrade the cloud to a newer version
without losing any of the deployed and provisioned resources.

The most difficult part of an upgrade is API and database changes. In
Dragonflow, the API is inferred from the database. Therefore, database
changes become the centre of the upgrade scenario.

This spec proposes a solution on how to upgrade a deployed cloud, without
breaking functionality, including incompatible database upgrades.

Assumptions during upgrade phase (the duration of upgrade procedure):

* DHCP, metadata service, and anything requiring the controller are allowed to
  stop working

* Modification to the network topology is allowed to fail

* Networking between ports should continue to work normally. Especially l2, l3,
  and security groups.

* Rollback is supported without loss of data before Neutron/Nova writes are
  re-enabled.

Proposed Change
===============

In this spec., we discuss cloud networking upgrade. The operator will initiate
and manage it (to make it easier, some tooling can be developed). The upgrade
will be done in the following steps:

#. Neutron and Dragonflow services are stopped on all cloud nodes.
#. Neutron and Dragonflow code is updated on all nodes.

  #. If new configuration is required, e.g. configuration options were added,
     it is performed at this stage.

#. On a single cloud controller node (i.e. one runnign Neutron server), the
   operator executes the upgrade utilities (first Neutron and then Dragonflow).

   #. If any of the upgrades fail, operator reverts package and configuration
      to prior version.

#. Neutron and Dragonflow services are started in the correct order.

Database Migration
------------------

Database migration process will perform the following:

* Locate all available migrations in the stevedore managed paths

* Locate all applied migrations from the north-bound database. Applied
  migrations (i.e. migrations that were applied in previous upgrades) are
  registered in the SchemaMigrationLog model below.

* Decide whether any migrations should be applied

  * If no migrations to apply, terminate.

* Take in-memory snapshot of the north-bound database.

* Iterate migrations ordered by their proposed date, and apply each one on the
  in-memory copy of the database.

 * If an error occurs, report and stop (nothing was written to the database).

 * If no errors occur, an entry is added to the migration table
   (SchemaMigrationLog, below), specifying the migration performed and the
   current date & time.

* Once all migrations are complete, copy in-memory database to actual database.
  Overwriting existing data.

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

Neutron Database Migration
--------------------------

Databse migration will be done using two migration scripts: Dragonflow
North-bound DB, and Neutron DB.

Both migrations will be run when the control plane is
offline. i.e. Neutron will not accept API requests, and the DF controllers
will be down.

The process will be as follows:

::

    1. Shut down Neutron servers and Dragonflow controllers
    2. Run migration scripts
       2.1. On Northbound Database
       2.2. On Neutron Database (As part of or after Neutron's migration scripts)
    3. Restart Dragonflow controllers and Neutron servers.

The order of 2.1. and 2.2. can be changed, since while everything is shut down
it should not make a difference.

Pros:

1. Upgrade is independendant of Neutron. If Neutron is not used, just
   skip step 2.2.

Cons:

1. Logic is duplicated in both Neutron migration and Dragonflow migration.

2. Sharing information between migrations is not trivial.

NB Data Model Impact
====================

A new model SchemaMigrationLog will be introduced:

+------------------------+---------------------------------------------+
|    Attribute Name      |               Description                   |
+========================+=============================================+
| id                     | Unique identity of the script               |
+------------------------+---------------------------------------------+
| release                | Release the upgrade script belongs to       |
+------------------------+---------------------------------------------+
| description            | Short description of the upgrade script     |
+------------------------+---------------------------------------------+
| proposed_at            | Time the migration script was implemented,  |
|                        | used to create some ordering between scripts|
+------------------------+---------------------------------------------+
| applied_at             | Time the script was executed                |
+------------------------+---------------------------------------------+

This model will keep a record of the 'migrations' (or upgrades) that were
already applied. The migration mechanism will use this table to see if a
migration script needs to be executed. It can also be used for troubleshooting
to see if the correct (or expected) migrations were applied.

References
==========

Neutron Alembic Migrations [1]_:

.. [1] https://docs.openstack.org/neutron/pike/contributor/alembic_migrations.html
