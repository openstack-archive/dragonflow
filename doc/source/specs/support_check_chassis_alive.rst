..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

====================================
Support checking if chassis is alive
====================================

https://blueprints.launchpad.net/dragonflow/+spec/is-chassis-alive-support

Chassis is important to some functionalities, for example, segments support,
router gateway. Dragonflow should provide a way to check if a chassis is
active. So that other functionalities can use it.

Problem Description
===================

Currently, Dragonflow doesn't provide a way to check if a chassis is active.
This causes several problems.

* Once a chassis is registered in Dragonflow Northbound Database, there is no
  way to unregister it, even if it goes down. This fact will increase the
  unnecessary burden to the Dragonflow Northbound Database and OpenFlow in
  each Dragonflow controller.

* The network segments support needs the information of if chassis is active.
  This involves the ml2 port binding and routed networks.

* To support router gateway in native Dragonflow, the information of if chassis
  is active is required. Because, either centralized router gateway or
  distributed router gateway, needs to run in active chassis.

Proposed Change
===============

Make Dragonflow controller report its timestamp to Dragonflow Northbound
Database periodly. Add a method to tell if a chassis is active.

The implementation will under the assumption that all the nodes in OpenStack
cloud have consistent time. This is a reliable assumption because it is
recommended to use NTP(Network Time Protocol) to properly synchronize services
among nodes, according to [#]_.

.. [#] http://docs.openstack.org/newton/install-guide-obs/environment-ntp.html

As distributed controller of SDN(software defined network), Dragonflow
controller can be used to monitor and manage other local services, for example,
Dragonflow L3 agent, metadata proxy, and other services in future. By using
[#]_ from OpenStack Neutron, it is easy to start/stop/check the local services.

.. [#] neutron.agent.linux.external_process.ProcessManager

Dragonflow controller can report the status of local services to Dragonflow
Northbound Database, when it reports its timestamp.

For the services that should run with neutron-server process, it could also
be managed by ProcessManager mentioned above.

Configuration Impact
--------------------

Add a new configuration option, *chassis_down_time*, which means that the
chassis will be considered as down if it doesn't report itself for such a
long time. The default value of *chassis_down_time* will be 75 seconds, which
should be at least more than twice of report_interval described below.

Add a new configuration option, *report_interval*. Dragonflow controller will
report timestamp to Dragonflow Northbound Database by using this option as
time interval. The default value of *report_interval* is 30 seconds, which
should not cause big impact to the performance of Dragonflow Northbound
Database.

NB Data Model Impact
--------------------

Add a new field called *timestamp* to Chassis in Dragonflow Northbound
Database. This field will not be exposed. The Chassis class in Dragonflow
Northbound will provide a new method called is_active. The new method will
compare *timestamp* of chassis and current time. If timestamp is older than
current time, and the gap is greater than *chassis_down_time*, the method
will return false.

Add a new field called *service_status* to Chassis in Dragonflow Northbound
Database. The status of local services will be recorded in this field.

The new DB cli commands that are mentioned below will show the Chassis status
according to the return value of this method. Administrator can then delete the
stale Chassis.

Other functionalities, for example ml2 port binding, can avoid using the stale
Chassis by checking the return value of this method. If the return value is
false, ml2 can report error on port binding. The details depend on the
implementation of other functionalities. This method just provides the
possibility to do that.

Publisher Subscriber Impact
---------------------------

Dragonflow controller should silently ignore the update of timestamp. Actually,
it should only concern about the IP address change of chassis once virtual
tunnel port is implemented at [#]_.

.. [#] https://blueprints.launchpad.net/dragonflow/+spec/virtual-tunnel-port-support

Dragonflow DB CLI Impact
------------------------

Dragonflow DB CLI should provide 2 commands.

#. A command to list chassis, administrator can use this command to check all
   chassis in the OpenStack Cloud. Also, an optional parameter will be added to
   the command. The optional parameter will provide the ability to filter out
   the active chassis or stale chassis.
#. A command to delete stale chassis. When administrator deletes chassis, the
   chassis delete event should be broadcasted to all Dragonflow controllers.
   Dragonflow controllers should clear local information of stale chassis when
   receive such event.

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

#. Make Dragonflow controller silently ignore the change of timestamp of
   chassis.
#. Make Dragonflow controller manage services other than itself.
#. Add configuration and make Dragonflow controller report to Dragonflow
   Northbound Database periodly.
#. Add commands to Dragonflow DB CLI.
