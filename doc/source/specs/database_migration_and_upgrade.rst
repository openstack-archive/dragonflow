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
and some compute nodes. You want to upgrade the cloud to latest and greatest
without losing all the deployed and provisioned resources.

The most difficult part of an upgrade is API and database changes. In
Dragonflow, the API is inferred from the database. Therefore, database
changes become the centre of the upgrade scenario.

This spec proposes a solution on how to upgrade a deployed cloud, without
breaking functionality, including incompatible database upgrades.

Assumptions during upgrade phase (the duration of upgrade procedure):

* DHCP, metadata service, or anything requiring the controller is allowed to
  stop working

* Network modification allowed to fail

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

  #. If new configuration is required, it is performed at this stage.

#. On a single host, the operator executed the upgrade utilities (first Neutron
   and then Dragonflow).

   #. If any of the upgrades fail, operator reverts package and configuration
      to prior version.

#. Neutron and Dragonflow services are started in the correct order.

Database Migration
------------------

Database migration process will perform the following:

* Locate all avaliable migrations in the stevedore managed paths
* Locate all applied migrations from the north-bound database
* Decide whether any migrations should be applied

  * If no migrations to apply, terminate.

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

Neutron Database Migration
--------------------------

There are several options as to how to align the migration with the Neutron
database.

Option 1: Two migration scripts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This option proposes that in addition to Dragonflow's migration scripts, we
also add Neutron migration scripts which update the Neutron database.

The process will be as follows:

::

    1. Shut down Neutron servers and Dragonflow controllers
    2. Run migration scripts
       2.1. On Northbound Database
       2.2. On Neutron Database (As part of or after Neutron's migration scripts)
    3. Restart Dragonflow controllers and Neutron servers.

The order of 2.1. and 2.2. can be changed, since while everything is shut down
it shuold make a difference.

Pros:

1. Upgrade is independendant of Neutron. If Neutron is not used, just skip step 2.2.

Cons:

1. Logic is duplicated in both Neutron migration and Dragonflow migration.

2. Sharing information between migrations is not trivial.

Option 2: Online Neutron Changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This option proposes that Dragonflow migration only handles the syntactic
differences only, e.g. renaming fields.

Changes that also affect the Neutron database will be written to a log, and
then executed via the Neutron API. The changes will then trickle back to the
Dragonflow database.

The process will be as follows:

::

    1. Shut down Neutron servers and Dragonflow controllers
    2. Run migration scripts on Northbound Databse
    3. Start up Neutron servers
    4. Run generated log on Neutron API
    5. Restart Dragonflow controllers

Pros:

1. No code duplication

2. Information can be shared

Cons:

1. Upgrade relies on Neutron. To remove this reliance, code must be duplicated.

NB Data Model Impact
====================

A new model SchemaMigration will be introduced:

::

    +------------------------+---------------------------------------------+
    |    Attribute Name      |               Description                   |
    +========================+=============================================+
    | id                     | Unique identity of the script               |
    +------------------------+---------------------------------------------+
    | release                | Release the upgrade belongs to              |
    +------------------------+---------------------------------------------+
    | description            | Short descrption of the upgrade             |
    +------------------------+---------------------------------------------+
    | proposed_at            | Time the migration script was implemented,  |
    |                        | used to create some ordering between scripts|
    +------------------------+---------------------------------------------+
    | applied_at             | Time the script was executed                |
    +------------------------+---------------------------------------------+

References
==========
