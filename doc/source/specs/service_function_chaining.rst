..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==========================================
Service Function Chaining
==========================================

https://blueprints.launchpad.net/dragonflow/+spec/service-function-chaining

Problem Description
===================

Service function deployment in a network that supports only destination based
routing can be very time consuming. It requires sophisticated topologies that
have to be mainatined manually outside of the tools offered by neutron.

Recently networking-sfc proposed a change in the API to allow definition of
service function chains and policy based routing (flow classifiers), based
on the architecture described in RFC 7665 [1]

Proposed Change
===============

Neutron SFC mechanism defines a sequence of port pairs (or groups of) that
represent a service function, and classifiers to filter incoming traffic. [2]

::

                                         +----------+
                                 Match   | Service  |
                                    +----> function +----+   +-------+
 +--------+       +------------+    |    | chain    |    +---> Dest. |
 | Source |       | Flow       +----+    +----------+    +---> port  |
 | port   +-------> classifier +----+                    |   +-------+
 +--------+       +------------+    | No match           |
                                    +--------------------+


This change will introduce the notion of service function chains to DragonFlow
database and will take advantge of NSH [3] and openvswitch to implement the
routing.

To implement this change we will introduce a new DF application responsible
for routing the SFC related traffic inside the pipeline and between the
controllers, its primary tasks will be:

+ Routing traffic from source ports into the SFC pipeline.
+ Implementing flow classifiers with flows inside OVS.
+ Encapsulating packets that match a classifier with the appropriate NSH header
  that maps to a correct service function chain, and popping the NSH header
  once packet reaches the end of the chain.
+ Routing traffic between SFs both locally and between controllers.


Service Path Identifier allocation
----------------------------------

SPI allocation will take place in the Neutron side, and to avoid conflict
between allocated IDs we should use the same method we use for port tunnel
keys, by allocating unique IDs through our database driver.

We should also reserve a certain range for locally managed SFCs, see Benefits
to DragonFlow section for more details.



Changes to the object model
---------------------------

This change will introduce and object that matches its design to the respective
objects in Neutron:

.. code-block:: json

 {
     "id": "ID of the SFC",
     "name": "Name of the SFC",
     "tenant_id": "Tenant ID of the SFC",
     "correlation_mechanism": "NSH",
     "service_path_id": "Identifier of this SFC",
     "service_path": [
         [
             {
                 "ingress_port_id": "ID of the ingress port for SF",
                 "egress_port_id": "ID on the egress port for SF"
             },
             "More service function instances"
         ],
         "More service function groups definitions"
     ]
     "flow_classifiers": [
         {
             "name": "Flow classifier name",
             "ether_type": "IPv4/IPv6",
             "protocol": "IP protocol",
             "source_cidr": "Source CIDR of incoming packets",
             "dest_cidr": "Destination CIDR of incoming packets",
             "source_transport_port": "[min, max]",
             "dest_transport_port": "[min, max]",
             "source_lport_id": "ID of source port",
             "dest_lport_id": "ID of destination port",
             "l7_parameters": "Dictionary of L7 parameters"
         },
         "More flow classifier definitions"
     ]
 }

Security concerns
-----------------
User deployed service functions have full control over the packets they produce
and can take advantge of that to inject invalid or malicious packets into our
network. For this matter, a valid packet is one that does not intend to harm
the network or its resources.

We can perform several checks on SF egress packets:

#. Check if the packet is NSH encapsulated, if it is not, apply the original
   pipeline (port sec, security groups, fw, ...)
#. Check that SPI on the packet maps to a valid SFC in the database that
   belongs to the same tenant as the service funcion.
#. Check that SI on the packet maps to the next hop in the SFC (Neutron's API
   does not take into account re-classification at service function nodes)

The following steps can be implemented using flows in OVS

::

 +------------+           +---------------+         +-------------+
 | SFC egress |  NSH      | NSH security  |         | NSH routing |
 | port       +-----------> checks        +--------->             |
 |            |           |               |         |             |
 +--------+---+           +---------------+         +-------------+
          |
          |               +---------------+
          |     Not NSH   | Regular       |
          +---------------> pipeline      |
                          |               |
                          +---------------+

Benefits to DragonFlow
----------------------
This change can help simplify dragonflow's pipeline, as now we can define our
apps (now service functions) with much less coupling to each other, and let the
service function app drive the messages between them.

For example, for each packet originating from the VM port on the controller, we
can define the following SFC:

* Port security
* Security groups
* Firewall
* Quality-of-Service
* etc

::

                +-------------------------------------+
  +------+      | Egress service function chain       |
  |  VM  |      |  +-----+  +----+  +----+  +-----+   |
  | port |------+->| Port|->| SG |->| FW |->| QoS |---+-->....
  +------+      |  | sec.|  | SF |  | SF |  | SF  |   |
                |  +-----+  +----+  +----+  +-----+   |
                +-------------------------------------+

Work Items
----------
#. Make sure openvswitch NSH patches [4] get merged
#. Implement MechDriver changes to accept the callbacks from networking-sfc
   and the relevant parts of north-bound API.
#. Implement the dragonflow controller app that manages the flows based on the
   SFCs relevant to the controller.
#. Implement SFC "port security" mechanism.

References
==========
[1] https://tools.ietf.org/html/rfc7665

[2] http://docs.openstack.org/developer/networking-sfc/api.html

[3] https://tools.ietf.org/html/draft-ietf-sfc-nsh-10

[4] https://github.com/yyang13/ovs_nsh_patches
