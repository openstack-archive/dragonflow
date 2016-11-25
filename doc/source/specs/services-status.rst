..
=================
Services Status
=================

https://blueprints.launchpad.net/dragonflow/+spec/services-status

This specs is being introduced, to keep the status of all the services
available all the time in database.

Problem Description
===================

This specs solves the following problem

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
Database periodically. Add common code, which can be used by all the service
to report their status.

The implementation will be under the assumption that all the nodes in OpenStack
cloud have consistent time.

Controller needs to report status of following services
  -> L3 agent
  -> metadata proxy
  -> local controller
  -> publisher service

Local controller status is planned to report its status in [#]_ blueprint

..[#] https://review.openstack.org/#/c/385719/

To avoid writing duplicate code, mentioned blueprint's code will be reused
for status reporting.

A generic module will be written, which takes name of the service as input
and does the tasks of reporting status to DB. Therefore L3 agent and metadata
proxy service can use the same module.

For publisher run with neutron-server process, it could also be managed by
ProcessManager and takes the responsibility of reporting status.

or

The same generic module(used for L3 agent or metadata service) can be used
for status of the service. It will resuse existing code and seems to be
clean way of doing it.

Configuration Changes:
----------------------

Add a new configuration option, *service_down_time* in df section, which means
that the service will be considered as down, if it doesn't report itself
for such a long time. The default value of *service_down_time* will be 80s
which should be at least more than three of *report_interval* described below.

Add a new configuration option, *service_report_interval*. Services will
report timestamp to Dragonflow Northbound Database by using this option as
time interval. The default value of *service_report_interval* is 25 seconds,
which should not cause big impact to the performance of Dragonflow Northbound
Database.

If code of chassis alive and ProcessManager report is used then
*service_down_time* and *service_report_interval* will not be applicable for
the respective services.

NB Data Model Impact
--------------------

A new table will be added in Dragonflow NB database, which contains following
information regarding each service
   -> id
   -> host or chassis   # Can be agreed after discussion
   -> binary or name   # Can be agreed after discussion
   -> disabled
   -> disabled_reason
   -> last_seen_up
   -> forced_down
   -> report_count

Publisher Subscriber Impact
---------------------------
Dragonflow controller should silently ignore all the updates on the new table.

Dragonflow DB CLI Impact
------------------------

df-db will utility will be provide following commands to the administrator
  -> service list:- List all the registered services
  -> service show:- Show detailed information of the service to fetch
  -> service enable:- Enable an already disabled service
  -> service disable:- Disable a service

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

-> Make Dragonflow controller silently ignore the changes in service table.
-> Add configuration and make Dragonflow services report to Dragonflow
   Northbound Database periodically.
-> Add commands to Dragonflow DB CLI.

References
==========

https://review.openstack.org/#/c/385719/8/doc/source/specs/support_check_chassis_alive.rst
http://docs.openstack.org/developer/dragonflow/specs/publish_subscribe_abstraction.html
https://specs.openstack.org/openstack/fuel-specs/specs/6.1/neutron-agents-local-reports.html
