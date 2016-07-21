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

The QoS of neutron provides a way to attach QoS policies to neutron ports
and networks. So we need to develop this feature to support it, but in this
patch we only support applying QoS policies to ports.

Proposed Change
===============

DragonFlow defines an object called qos to implement the port QoS. The
qos object has some attributes listed in the followed table:

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
|   qos_policy       |   QoS policy object                         |
|                    |                                             |
+--------------------+---------------------------------------------+

The qos_policy includes some attributes listed in the followed table:

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

The type of qos includes "all" and "dscp". Besides the basic attributes
id, type, etc, the qos may have all of the attributes in the qos_policy
when the type of qos is "all" and only have the dscp attribute in the
qos_policy when the type of qos is "dscp".

QoS Notification Driver
-----------------------

The QoS plugin which is one of the neutron service plugins handles the CRUD
of QoS policies and rules. We will convert the QoS policies and rules to qos
object in the qos_notification_driver of DragonFlow and deal with the CRUD
operations.

ML2 Mechanism Driver
--------------------

When port updates related to a qos, the DragonFlow ML2 driver will
save the relationship of port and qos in DF DB. And when port detaches from
a qos, it will delete the relationship.

QoS App
-------

The QoS app is a module of local controller which implements the logic of
QoS. The app concerns about the qos updated and port updated northbound events
and also care about the southbound port events which include port created and
port removed.

Port Created
------------

When the QoS app receives the port created event, it will get the qos attached
to the port from the DB store, then set the tx_burstSize and tx_averateLimit
of the qos to ingress_policing_bust and ingress_policing_rate of the
corresponding interface on the OVS for limiting the bandwidth of egress traffic
of the port. In addition, the QoS app creates a queue attached to the port and
sets the rx_averateLimit and dscp of qos to other_config and dscp of the queue
on the OVS for limiting the bandwidth of ingress traffic of the port.

Port Removed
------------

When the QoS app receives the port removed event, it will delete the
corresponding qos configuration of the removed port on the local host, for
example, unset the ingress_policy of the interface and the other_config and
dscp of the queue.

Port Updated
------------

The port updated event can show three scenarios:
1. port applies a qos
2. port applies a new qos
3. port applies no qos

For scenario 1, the QoS app will set the corresponding configuration of the qos
for the port, the configuration is similar with the description in
"Port Created" section above.

For scenario 2, the Qos app will update the configuration according to the new
qos object.

For scenario 3, the Qos app will delete the configuration for the port.


Qos Object Delete
-----------------

It is not permitted to delete the qos object attached to some ports. If no ports
apply the qos, it can be deleted from the DragonFlow DB.

Qos Object Update
-----------------

When updating the qos object, the new value of bandwidth will be propagated
to all the ports which apply the qos object.


References
==========
http://specs.openstack.org/openstack/neutron-specs/specs/liberty/qos-api-extension.html
https://review.openstack.org/#/c/331932
