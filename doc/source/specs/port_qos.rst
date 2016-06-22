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
and networks. So, DrangonFlow need to develop this feature to support them.
Currently, DragonFlow only supports applying QoS policies to ports.

Proposed Change
===============
DragonFlow defines a object called qos to implement the port QoS. The
qos has some attributes which are id¡¢type which includes all and dscp¡¢
tenant_id¡¢description and qos_policies which include tx_averateLimit¡¢
tx_burstSize¡¢rx_averateLimit¡¢rx_burstSize and dscp. The tx_averateLimit
and tx_burstSize used to limit the bandwidth of egress direction (from the
vm point of view), the rx_averateLimit and rx_burstSize used to limit the
bandwidth of ingress direction. DragonFlow doesn't use the attribute dscp
in this patch.


ML2 Mechanism Driver
--------------------
The DragonFlow ML2 driver save the qos object to DragonFlow DB.

QoS App
-------
The QoS app is a module of local controller which implement the logic of
QoS.The app subscribe the northbound events qos object events which
include updating qos and updating port and care the southbound port events
which include port online and port offline.

Port Online
-----------
when the QoS app receives the port online event, it will get the qos attached
to the port from the DB store, then set the tx_burstSize and tx_averateLimit
of the qos to ingress_policing_bust and ingress_policing_rate of interface on
the OVS for limiting the bandwidth of egress direction of the port. In addition,
the QoS app creates a queue attached to the port and set the rx_averateLimit of
qos to other_config of queue on the OVS for limiting the bandwidth of ingress
direction of the port.

Port Offline
------------
when the QoS app receives the port offline event, it will unset the bandwidth
limiting of the port.

Port Updating
-------------
The Port Updating event can show three scenarios:
1.port applys a qos
2.port applys a new qos
3.port applys no qos
For all the scenarios, the QoS app will do nothing if the port's status is down.
when the port's status is up, the QoS app will do something like the port online
event for scenario 1 and do something like the qos object updating event for
scenario 2 and do something like the port offline event for scenario 3.


Qos Object Delete
-----------------
It is not permit to delete the qos object attached to some ports.

Qos Object Update
-----------------
when Updating the qos object, the new value of bandwidth will be propagated
to all the ports which apply the qos object.


References
==========
[1] http://specs.openstack.org/openstack/neutron-specs/specs/liberty/qos-api-extension.html