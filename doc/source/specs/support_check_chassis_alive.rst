..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=================================
Support check if chassis is alive
=================================

https://blueprints.launchpad.net/dragonflow/+spec/is-chassis-alive-support

Chassis is important to some functionalities, for example, segments support,
router gateway. Dragonflow should provide a way to check if a chassis is alive.
So that other functionalities can use it.

Problem Description
===================

Currently, Dragonflow doesn't provide a way to check if a chassis is alive.
This causes several problems.

* Once a chassis is registered in Dragonflow Northbound Database, there is no
  way to unregister it, even if it goes down. This fact will increase the
  unnecessary burden to the Dragonflow Northbound Database.

* The network segments support needs the information of if chassis is alive.
  This involves to the ml2 port binding and routed networks.

* To support router gateway in native Dragonflow, the information of if chassis
  is alive is required. Because, either centralized router gateway or
  distributed router gateway, needs to run in alive chassis.

Proposed Change
===============

Make Dragonflow controller report its timestamp to Dragonflow Northbound
Database periodly. Add a method to tell if a chassis is alive.

The implementation will under the assumption that all the nodes in OpenStack
cloud have consistent time. This is a reliable assumption because it is
recommended to use NTP(Network Time Protocol) to properly synchronize services
among nodes, according to [#]_.

.. [#] http://docs.openstack.org/newton/install-guide-obs/environment-ntp.html

Configuration Impact
--------------------

Add a new configuration option, *chassis_down_time*, which means that the
chassis will be considered as down if it doesn't report itself for such a
long time.

The configuration option *report_interval* from OpenStack Neutron will be used.
Chassis will use this value as the interval to report its timestamp to
Dragonflow Northbound Database. The default value of *report_interval* is 30
seconds, which should not cause big impact to the performance of Dragonflow
Northbound Database.

NB Data Model Impact
--------------------

Add a new field called timestamp to Chassis in Dragonflow Northbound Database.
This field will not be exposed. The Chassis class in Dragonflow Northbound will
provide a new method called is_active. The new method will compare timestamp of
chassis and current time. If timestamp is older than current time, and the gap
is greater than *chassis_down_time*, the method will return false.

Publisher Subscriber Impact
---------------------------

Dragonflow controller should silently ignore the update of timestamp. Actually,
it should only concern about the IP address change of chassis once virtual
tunnel port is implemented at [#]_.

.. [#] https://blueprints.launchpad.net/dragonflow/+spec/virtual-tunnel-port-support

Dragonflow DB CLI Impact
------------------------

Dragonflow DB CLI should provide 2 commands.

#. A command to list stale chassis.
#. A command to delete stale chassis.

So that administrator can clean the stale chassis.

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
  `xiaohhui <https://launchpad.net/~xiaohhui>`_

Work Items
----------

#. Make Dragonflow controller silently ingore the change of timestamp of
   chassis.
#. Add configuration and make Dragonflow controller report to Dragonflow
   Northbound Database periodly.
#. Add commands to Dragonflow DB CLI.
