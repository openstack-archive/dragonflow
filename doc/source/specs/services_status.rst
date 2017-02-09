===============
Services Status
===============

https://blueprints.launchpad.net/dragonflow/+spec/services-status

This spec is introduced to keep the status of all the services
available all the time in database.

Problem Description
===================

This spec solves the following problems

* To view services status in cluster, administrator does not have any tool.
  This spec enables administrators to view status of the services in the
  cluster from any node having df-db command available.

* Other services can take advantage of services status to schedule tasks.

* It enables administrator to put a node in maintenance mode or stop a service
  from participating in processing.

* This spec will provide support in future, for making services highly
  available.


Proposed Change
===============

Make Dragonflow services report its timestamp to Dragonflow Northbound
Database periodically. Add common code, which can be used by all the services
to report their status.

The implementation will be under the assumption that all the nodes in OpenStack
cloud have consistent time.

Following services report its own status
  1. L3 agent
  2. metadata proxy
  3. local controller
  4. publisher service

Local controller status is planned to report its status in [#]_ blueprint

.. [#] https://review.openstack.org/#/c/385719/

To avoid writing duplicate code, mentioned blueprint's code will be changed
to reuse the code of proposed blueprint.


A generic module will be written, which takes name of the service as input
and does the tasks of reporting status to DB. Therefore L3 agent, local
controller, publisher and metadata proxy service can use the same module.

Enable and disable a service makes the service down in NB database only. It
does not impact any app. Later it can be extended to support operations in
case a service is enabled and disabled.

Configuration Changes
---------------------

Add a new configuration option, *service_down_time* in df section, which means
that the service will be considered as down, if it doesn't report itself
for such a long time. The default value of *service_down_time* will be 80s
which should be at least more than three of *report_interval* described below.

Add a new configuration option, *report_interval*. Services will report
timestamp to Dragonflow Northbound Database by using this option as time
interval. The default value of *report_interval* is 25 seconds, which should
not cause big impact to the performance of Dragonflow Northbound
Database.

NB Data Model Impact
--------------------

A service table will be added in Dragonflow NB database, which contains following
information regarding each service.

::

  +------+-------------------+--------------------------------------------------+
  | S.No |   field           |  Description                                     |
  +======+===================+==================================================+
  | 1.   |  id               | ID of the service(UUID)                          |
  +------+-------------------+--------------------------------------------------+
  | 2.   |  chassis          | hostname                                         |
  +------+-------------------+--------------------------------------------------+
  | 3.   |  binary           | Name of the service                              |
  +------+-------------------+--------------------------------------------------+
  | 4.   |  disabled         | Represent whether explicitly disabled or not     |
  +------+-------------------+--------------------------------------------------+
  | 5.   |  disabled_reason  | Reason given when disabling the service          |
  +------+-------------------+--------------------------------------------------+
  | 6.   |  last_seen_up     | Last time stamp reported by the service          |
  +------+-------------------+--------------------------------------------------+

Plan is to store information on following bassis, if possible.

::

  {
    "binary1": {
      "chassis1":
        {
          "id": UUID,
          "chassis": hostname,
          "binary": service_name,
          "disabled": True/False,
          "disabled_reason": reason,
          "last_seen_up": timestamp,
          "report_count": count(int)"
        },
      "chassis2":
        {
          "id": UUID,
          "chassis": hostname,
          "binary": service_name,
          "disabled": True/False,
          "disabled_reason": reason,
          "last_seen_up": timestamp,
          "report_count": count(int)"
        },
        -
        -
        -
    },
    "binary2": {
      "chassis1":
        {
          "id": UUID,
          "chassis": hostname,
          "binary": service_name,
          "disabled": True/False,
          "disabled_reason": reason,
          "last_seen_up": timestamp,
          "report_count": count(int)"
        },
      "chassis2":
        {
          "id": UUID,
          "chassis": hostname,
          "binary": service_name,
          "disabled": True/False,
          "disabled_reason": reason,
          "last_seen_up": timestamp,
          "report_count": count(int)"
        },
        -
        -
        -
    },
    -
    -
    -
  }

The assumption for the above data management is, there can be only one instance of
a service on a node that has to be registered.

It does not add any overhead during status reporting, services has to report their
binary and host. And updation of service status can be done easily in constant time.

It provides benefit for queries asking for example "list all the host running
publishers." or "list all the publishers in the cluster". These queries seems to be
more frequent as load has to be balanced between services etc.

Publisher Subscriber Impact
---------------------------
Dragonflow controller should silently ignore all the updates on the new table.

Dragonflow DB CLI Impact
------------------------

df-db utility will provide following commands to the administrator.

::

  +------+------------------+----------------------------------------------------+
  | S.No | command          | Description                                        |
  +======+==================+====================================================+
  |  1.  | service list     | List all the registered services                   |
  +------+------------------+----------------------------------------------------+
  |  2.  | service show     | Show detailed information of the service to fetch  |
  +------+------------------+----------------------------------------------------+
  |  3.  | service enable   | Enable an already disabled service                 |
  +------+------------------+----------------------------------------------------+
  |  4.  | service disable  | Disable a service                                  |
  +------+------------------+----------------------------------------------------+

Based on *service_down_time* configuration and last_seen_up, disabled field
from database decide state of the service.


Dragonflow Applications Impact
------------------------------

None

Installed flows Impact
----------------------

None

Implementation
==============

Assignee(s)
-----------

Primary assignee:
  `rajiv-kumar <https://launchpad.net/~rajiv-kumar>`_

Work Items
----------

1. Make Dragonflow controller silently ignore the changes in service table.
2. Add configuration and make Dragonflow services report to Dragonflow
   Northbound Database periodically.
3. Add commands to Dragonflow DB CLI.

References
==========

https://review.openstack.org/#/c/385719/8/doc/source/specs/support_check_chassis_alive.rst

http://docs.openstack.org/developer/dragonflow/specs/publish_subscribe_abstraction.html

https://specs.openstack.org/openstack/fuel-specs/specs/6.1/neutron-agents-local-reports.html
