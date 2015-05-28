SDN based Virtual Router add-on for Neutron OpenStack


* Free software: Apache license
* Homepage:  http://launchpad.net/dragonflow
* Source: http://git.openstack.org/cgit/stackforge/dragonflow
* Bugs: http://bugs.launchpad.net/dragonflow

Documentation:
--------------
* `Solution Overview Presentation <http://www.slideshare.net/gampel/dragonflow-sdn-based-distributed-virtual-router-for-openstack-neutron>`_

* `Solution Overview Blog Post  <http://blog.gampel.net/2015/01/neutron-dvr-sdn-way.html>`_

* `Deep-Dive Introduction 1 Blog Post <http://galsagie.github.io/sdn/openstack/ovs/dragonflow/2015/05/09/dragonflow-1/>`_

* `Deep-Dive Introduction 2 Blog Post <http://galsagie.github.io/sdn/openstack/ovs/dragonflow/2015/05/11/dragonflow-2/>`_

* `Kilo-Release Blog Post  <http://blog.gampel.net/2015/01/dragonflow-sdn-based-distributed.html>`_


Overview
--------
Dragonflow is an implementation of a fully distributed virtual router for OpenStack Neutron, which is based on a Software-Defined Network Controller (SDNC) design.

The main purpose of Dragonflow is to simplify the management of the virtual router, while improving performance, scale and eliminating single point of failure and the notorious network node bottleneck.

The proposed method is based on the separation of the routing control plane from the data plane.
This is accomplished by implementing the routing logic in distributed forwarding rules on the virtual switches.
In OpenFlow these rules are called flows. To put this simply, the virtual router is implemented using OpenFlow flows.

Dragonflow eliminates the use of namespaces in contrast to the standard DVR. A diagram showing Dragonflow components and overall architecture can be seen here:

.. image:: https://raw.githubusercontent.com/stackforge/dragonflow/master/doc/images/df_components.jpg
    :alt: Solution Overview
    :width: 600
    :height: 525
    :align: center


Perhaps the most important part of the solution is the OpenFlow pipeline which we install into the integration bridge upon bootstrap.
This is the flow that controls all traffic in the OVS integration bridge `(br-int)`.
The pipeline works in the following manner:

::

    1) Classify the traffic
    2) Forward to the appropriate element:
        1. If it is ARP, forward to the ARP Responder table
        2. If routing is required (L3), forward to the L3 Forwarding table
           (which implements a virtual router)
        3. All L2 traffic and local subnet traffic are offloaded to the NORMAL pipeline handled by ML2
        4. North/South traffic is forwarded to the network node (SNAT)


The following diagram shows the multi-table OpenFlow pipeline installed into the OVS integration bridge `(br-int)` in order to represent the virtual router using flows only:


.. image:: https://raw.githubusercontent.com/stackforge/dragonflow/master/doc/images/df_of_pipeline.jpg
    :alt: Pipeline
    :width: 600
    :height: 400
    :align: center



A detailed blog post describing the solution can be found Here_.

.. _Here: http://blog.gampel.net/2015/01/neutron-dvr-sdn-way.html


How to Install
--------------
`Installation Guide <https://github.com/stackforge/dragonflow/tree/master/doc/source>`_

`DevStack Single Node Configuration  <https://github.com/stackforge/dragonflow/tree/master/doc/source/single-node-conf>`_

`DevStack Multi Node Configuration  <https://github.com/stackforge/dragonflow/tree/master/doc/source/multi-node-conf>`_

Prerequisites
-------------
Install DevStack with Neutron ML2 as core plugin
Install OVS 2.3.1 or newer

Features
--------

* APIs for routing IPv4 East-West traffic
* Performance improvement for inter-subnet network by removing the amount of kernel layers (namespaces and their TCP stack overhead)
* Scalability improvement for inter-subnet network by offloading L3 East-West routing from the Network Node to all Compute Nodes
* Reliability improvement for inter-subnet network by removal of Network Node from the East-West traffic
* Simplified virtual routing management
* Support for all type drivers GRE/VXLAN/VLAN
* Support for centralized shared public network (SNAT) based on the legacy L3 implementation
* Support for centralized floating IP (DNAT) based on the legacy L3 implementation
* Support for HA, in case the connection to the Controller is lost, fall back to the legacy L3 implementation until recovery. Reused all the legacy L3 HA. (Controller HA will be supported in the next release).
* Supports for centralized IPv6 based on the legacy L3 implementation

TODO
----

* Add support for North-South L3 IPv4 distribution (SNAT and DNAT)
* Add support for IPv6
* Support for multi controllers solution
Full description can be found in the project `Blueprints  <https://blueprints.launchpad.net/dragonflow>`_

