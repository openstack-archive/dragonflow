==================
Distributed DHCP
==================

Current Neutron Reference Implementation
=========================================
The DHCP server is implemented using the Dnsmasq server
running in a namespace on the newtork-node per tenant subnet
that is configured with DHCP enabled.

Currently High availability is achieved by running multiple Dnsmasq
servers on multiple Network nodes.

There is a namespace with Dnsmasq server per tenant subnet

Problems with current DHCP implementation:

1) Management and Scalability
   - Need to configure and mange multiple Dnsmasq instances
2) Centralize solution depended on the network node

DHCP agent
-----------
Same Concept as L3 agent and namespaces for virtual router.
Using black boxes that implement functionality and using them as the IaaS
backbone implementation


Distributed DHCP In Dragonflow
===============================
Dragonflow distribute DHCP policy/configuration using the pluggable DB.
Each controller read this DB and install hijacking OVS flows for DHCP traffic
and send that traffic to the controller.

The controller dispatch this to the local DHCP application which answer with local
DHCP acks.

The following diagrams demonstrate this process:

.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/dhcp1.jpg
    :alt: Distributed DHCP 1
    :width: 600
    :height: 525
    :align: center

.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/dhcp2.jpg
    :alt: Distributed DHCP 1
    :width: 600
    :height: 525
    :align: center