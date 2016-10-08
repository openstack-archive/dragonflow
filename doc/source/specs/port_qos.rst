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

DragonFlow defines an object called QoS to implement the port QoS. The
QoS object has some attributes listed in the followed table:

+--------------------+---------------------------------------------+
|   Attribute Name   |               Description                   |
+====================+=============================================+
|   id               |   identify                                  |
+--------------------+---------------------------------------------+
|   type             |   type of QoS                               |
+--------------------+---------------------------------------------+
|   tenant_id        |   tenant ID of QoS object owner             |
+--------------------+---------------------------------------------+
|   description      |   QoS description                           |
+--------------------+---------------------------------------------+
|   qos_policy       |   QoS policy object                         |
+--------------------+---------------------------------------------+

The qos_policy includes some attributes listed in the followed table:

+--------------------+---------------------------------------------+
|   Attribute Name   |               Description                   |
+====================+=============================================+
|   tx_averateLimit  |   bandwidth limit of egress direction       |
+--------------------+---------------------------------------------+
|   tx_burstSize     |   burst size of egress direction            |
+--------------------+---------------------------------------------+
|   rx_averateLimit  |   bandwidth limit of ingress direction      |
+--------------------+---------------------------------------------+
|   rx_burstSize     |   burst size of ingress direction           |
+--------------------+---------------------------------------------+
|   dscp             |   Differentiated Services Code Point        |
+--------------------+---------------------------------------------+

The egress and ingress directions are from the VM's point of view.

The type of QoS includes "all" and "dscp". Besides the basic attributes
id, type, etc, the QoS may have all of the attributes in the qos_policy
when the type of QoS is "all" and only have the dscp attribute in the
qos_policy when the type of QoS is "dscp".

QoS Notification Driver
-----------------------

QoS plugin uses "message_queue" as default notification driver. Dragonflow
will add a new notification driver named "qos_notification_driver" to deal
with the CRUD operations of QoS policies.

If you want to use ML2 as core plugin and use dragonflow as ML2 mech driver,
you should edit neutron.conf file to configure
"notification_drivers = df_notification_driver" in [QoS] section.

You can see the implement of qos_notification_driver in patch:
https://review.openstack.org/#/c/331932/

ML2 Mechanism Driver
--------------------

When port updates related to a QoS, the DragonFlow ML2 driver will save the
relationship of port and QoS in DF DB. When port detaches from a QoS, it will
delete the relationship.

QoS App
-------

The QoS app is a module of local controller which implements the logic of
QoS. The app concerns about the QoS updated and port updated northbound events
and also cares about the southbound port events which include port created and
port removed.

Port Created
------------

When the QoS app receives the port created event, it will get the QoS attached
to the port from the DB store, then set the tx_burstSize and tx_averateLimit
of the QoS to ingress_policing_bust and ingress_policing_rate of the
corresponding interface on the OVS for limiting the bandwidth of egress traffic
of the port. In addition, the QoS app creates a queue attached to the port and
sets the rx_averateLimit and dscp of QoS to other_config and dscp of the queue
on the OVS for limiting the bandwidth of ingress traffic of the port.

Port Removed
------------

When the QoS app receives the port removed event, it will delete the
corresponding QoS configuration of the removed port on the local host, for
example, delete the QoS and queue attached to the removed port on the OVS.

Port Updated
------------

The port updated event can show three scenarios:

1. port applies a QoS

2. port applies a new QoS

3. port applies no QoS

For scenario 1, the QoS app will set the corresponding configuration of the QoS
for the port, the configuration is similar with the description in
"Port Created" section above.

For scenario 2, the QoS app will update the configuration according to the new
QoS object.

For scenario 3, the QoS app will delete the configuration for the port.


QoS Object Delete
-----------------

It is not permitted to delete the QoS object attached to some ports. If no ports
apply the QoS, it can be deleted from the DragonFlow DB.

QoS Object Update
-----------------

When updating the QoS object, the new value of bandwidth will be propagated
to all the ports which apply the QoS object.


References
==========

http://specs.openstack.org/openstack/neutron-specs/specs/liberty/qos-api-extension.html

https://review.openstack.org/#/c/331932
