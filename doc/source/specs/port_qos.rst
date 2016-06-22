..
  This work is licensed under a Creative Commons Attribution 3.0 Unported
  License.

  http://creativecommons.org/licenses/by/3.0/legalcode

========
Port QoS
========

https://blueprints.launchpad.net/dragonflow/+spec/qos-app

This spec describes the design of port QoS of DragonFlow.

Problem Description
===================
The QoS of neutron provides a way to attach QoS policies to neturon ports
and networks. So we need to develop this feature to support it, but in this
patch we only support applying QoS policies to ports.

Proposed Change
===============
DragonFlow defines an object called qos to implement the port QoS. The
qos has some attributes listed in the followed table:

+--------------------+---------------------------------------------+
|   attribute name   |               description                   |
|                    |                                             |
+------------------------------------------------------------------+
|   id               |   identify                                  |
|                    |                                             |
+------------------------------------------------------------------+
|   type             |   type of QoS                               |
|                    |                                             |
+------------------------------------------------------------------+
|   tenant_id        |   tenant ID of QoS object owner             |
|                    |                                             |
+------------------------------------------------------------------+
|   description      |   QoS description                           |
|                    |                                             |
+------------------------------------------------------------------+
|   qos_policies     |   QoS policies                              |
|                    |                                             |
+--------------------+---------------------------------------------+

The qos_policies include some attributes listed in the followed table:

+--------------------+---------------------------------------------+
|   attribute name   |               description                   |
|                    |                                             |
+------------------------------------------------------------------+
|   tx_averateLimit  |   bandwidth limit of egress direction       |
|                    |                                             |
+------------------------------------------------------------------+
|   tx_burstSize     |   burst size of egress direction            |
|                    |                                             |
+------------------------------------------------------------------+
|   rx_averateLimit  |   bandwidth limit of ingress direction      |
|                    |                                             |
+------------------------------------------------------------------+
|   rx_burstSize     |   burst size of ingress direction           |
|                    |                                             |
+------------------------------------------------------------------+
|   dscp             |   Differentiated Services Code Point        |
|                    |                                             |
+--------------------+---------------------------------------------+

The egress and ingress directions are from the VM point of view.

The type of QoS includes "all" and "dscp". Excepting the basic attributes
id、type etc, the qos object may have all of the attributes in the qos_policies
when the type of QoS is "all" and only have the dscp attribute in the
qos_policies when the type of QoS is "dscp".

QoS Notification Driver
----------
The QoS plugin which is one of the neutron service plugins handles the CRUD
of QoS policies and rules. We will convert the QoS policies and rules to qos
object in the qos_notification_driver of DragonFlow and deal with the CRUD of qos.

ML2 Mechanism Driver
--------------------
When port updates related to a qos, the DragonFlow ML2 driver will
notify the DragonFlow DB to save the relationship of port and qos.

QoS App
-------
The QoS app is a module of local controller which implements the logic of
QoS. The app subscribes the northbound events related to qos object which
include qos and port updated and care about the southbound port events
which include port created and port removed.

Port Created
-----------
When the QoS app receives the port created event, it will get the qos attached
to the port from the DB store, then set the tx_burstSize and tx_averateLimit
of the qos to ingress_policing_bust and ingress_policing_rate of interface on
the OVS for limiting the bandwidth of egress traffic of the port. In addition,
the QoS app creates a queue attached to the port and set the rx_averateLimit
and dscp of qos to other_config and dscp of queue on the OVS for limiting the
bandwidth of ingress traffic of the port.

Port Removed
------------
When the QoS app receives the port removed event, it will unset the bandwidth
limiting of the port.

Port Updated
-------------
The port updated event can show three scenarios:
1.port applys a qos
2.port applys a new qos
3.port applys no qos
The QoS app will do something like the port created event for scenario 1 and
do something like the qos object updated event for scenario 2 and do something
like the port removed event for scenario 3.


Qos Object Deleted
-----------------
It is not permitted to delete the qos object attached to some ports. If no port
apply the qos, it can be deleted from the DragonFlow DB.

Qos Object Updated
-----------------
When updating the qos object, the new value of bandwidth will be propagated
to all the ports which apply the qos object.


References
==========
http://specs.openstack.org/openstack/neutron-specs/specs/liberty/qos-api-extension.html
