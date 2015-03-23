SDN based Virtual Router add-on for Neutron OpenStack


* Free software: Apache license
* Homepage:  http://launchpad.net/dragonflow
* Documentation: http://goo.gl/rq4uJC
* Source: http://git.openstack.org/cgit/stackforge/dragonflow
* Bugs: http://bugs.launchpad.net/dragonflow

Overview
--------
Dragonflow is an implementation of a fully distributed virtual router for OpenStack Neutron, which is based on a Software-Defined Network Controller (SDNC) design.

The main purpose of Dragonflow is to simplify the management of the virtual router, while improving performance, scale and eliminating single point of failure and the notorious network node bottleneck.

The proposed method is based on the separation of the routing control plane from the data plane.
This is accomplished by implementing the routing logic in distributed forwarding rules on the virtual switches.
In OpenFlow these rules are called flows. To put this simply, the virtual router is implemented using OpenFlow flows.

Dragonflow eliminate the use of namespaces in contrast to the standard DVR, a diagram showing Dragonflow components and overall architecture can be seen here:

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
https://github.com/stackforge/dragonflow/tree/master/doc/source

Prerequisites
-------------
Install DevStack with Netron ML2 as core plugin
Install OVS 2.3.1 or newer

Features
--------

* APIs for routing IPv4 East-West traffic
* Performance improvement for inter-subnet network by removing the amount of kernel layers (namespaces and their TCP stack overhead)
* Scalability improvement for inter-subnet network by offloading L3 East-West routing from the Network Node to all Compute Nodes
* Reliability improvement for inter-subnet network by removal of Network Node from the East-West traffic
* Simplified virtual routing management
* Supports all type drivers GRE/VXLAN (Currently doesnt support VLAN)

TODO
----

* Add support for North-South L3 IPv4 distribution (SNAT and DNAT)
* Remove change impact on Neutron L2 Agent by switching to OVSDB command for bootstrap sequence (set-controller and install arp responder)
* Add support for IPv6
* Support for multi controllers solution

