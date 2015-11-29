Centralized Dragonflow
######################

Overview
--------
Dragonflow is an implementation of a fully distributed virtual router for
OpenStack Neutron that follows a Software Defined Network (SDN) Controller 
design.

The *Centralized* version of Dragonflow is intended as a 100% replacement
to the `Neutron DVR <https://wiki.openstack.org/wiki/Neutron/DVR>`_, with 
some advantages such as greatly simplified management of the virtual router,
improved performance, stability and scalability.

Architecture
------------

Dragonflow SDN architecture is based on the separation of the network control 
plane and data plane. This is accomplished by implementing the service logic
as a pipeline of {match ,action} OpenFlow flows that are executed in the data 
plane by the forwarding engine in the virtual switch (we rely on OVS).

By leveraging these programmatic capabilities and the distributed nature of
the virtual switches (i.e. one runs on each compute node), we were able to
consistently remove other "moving parts" from the OpenStack deployment, and
replace them with OpenFlow pipelines.

The benefits in this approach are twofold:

1. Fewer running processes == simpler maintenance == more stable environment
2. Services run truly distributed, removing the need to trombone traffic to
   a service node, therefore eliminating undesirable bottlenecks and greatly
   improving the ability to scale the environment to larger number of VMs
   and compute nodes

The Hybrid Reactive-Proactive Model
===================================

Dragonflow makes extensive use of the reactive OpenFlow behavior, in which 
the forwarding element (i.e. the virtual switch) forwards unmatched packets 
to the software path that leads to the SDN controller.

Combining this extremely powerful capability with carefully-constructed 
proactively-deployed pipelines enabled us to balance between 
functionality-rich slow-path logic and blazing-fast match and action engine.

Deployment Models
=================

The following diagram illustrates the main Dragonflow service components, in
its *Centralized* deployment model.

Centralized Dragonflow
^^^^^^^^^^^^^^^^^^^^^^

.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/df_components.jpg
    :alt: Solution Overview
    :width: 750
    :align: center

The main principle of this model is that the Dragonflow controller is 
deployed in one or several main locations and is separate from the
virtual switches that it manages.

The virtual switches connect to Dragonflow controller in OpenFlow and
are remote managed.

This model is suitable for small-to-medium deployments, with moderate
rate of new "VM-to-VM" connection establishments.

Advanced Services
=================

Distributed Virtual Router
^^^^^^^^^^^^^^^^^^^^^^^^^^

The Dragonflow distributed virtual router is implemented using OpenFlow 
flows.

This allowed us to eliminate the use of namespaces, which was both slow
(additional IP stack) and harder to maintain (more OS-level artifacts). 

Perhaps the most important part of the solution is the OpenFlow pipeline which
we install into the integration bridge upon bootstrap. This is the flow that
controls all traffic in the OVS integration bridge `(br-int)`. The pipeline
works in the following manner:

::

    1) Classify the traffic
    2) Forward to the appropriate element:
        1. If it is ARP, forward to the ARP Responder table
        2. If routing is required (L3), forward to the L3 Forwarding table
           (which implements a virtual router)
        3. All L2 traffic and local subnet traffic are offloaded to the NORMAL
           pipeline handled by ML2
        4. North/South traffic is forwarded to the network node (SNAT)


The following diagram shows the multi-table OpenFlow pipeline installed into
the OVS integration bridge `(br-int)` in order to represent the virtual router
using flows only:


.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/df_of_pipeline.jpg
    :alt: Pipeline
    :width: 650
    :align: center



A detailed blog post describing the solution can be found Here_.

.. _Here: http://blog.gampel.net/2015/01/neutron-dvr-sdn-way.html

Documentation
-------------

* `Solution Overview Presentation <http://www.slideshare.net/gampel/dragonflow-sdn-based-distributed-virtual-router-for-openstack-neutron>`_

* `Solution Overview Blog Post  <http://blog.gampel.net/2015/01/neutron-dvr-sdn-way.html>`_

* `Deep-Dive Introduction 1 Blog Post <http://galsagie.github.io/sdn/openstack/ovs/dragonflow/2015/05/09/dragonflow-1/>`_

* `Deep-Dive Introduction 2 Blog Post <http://galsagie.github.io/sdn/openstack/ovs/dragonflow/2015/05/11/dragonflow-2/>`_

* `Kilo-Release Blog Post  <http://blog.gampel.net/2015/01/dragonflow-sdn-based-distributed.html>`_
 
How to Install
--------------

`Installation Guide <https://github.com/openstack/dragonflow/tree/master/doc/source/centralized_readme.rst>`_

`DevStack Single Node Configuration  <https://github.com/openstack/dragonflow/tree/master/doc/source/single-node-conf>`_

`DevStack Multi Node Configuration  <https://github.com/openstack/dragonflow/tree/master/doc/source/multi-node-conf>`_

Prerequisites
-------------

Install DevStack with Neutron ML2 as core plugin
Install OVS 2.3.1 or newer

Features
--------

* APIs for routing IPv4 East-West traffic
* Performance improvement for inter-subnet network by removing the amount of
  kernel layers (namespaces and their TCP stack overhead)
* Scalability improvement for inter-subnet network by offloading L3 East-West
  routing from the Network Node to all Compute Nodes
* Reliability improvement for inter-subnet network by removal of Network Node
  from the East-West traffic
* Simplified virtual routing management
* Support for all type drivers GRE/VXLAN/VLAN
* Support for centralized shared public network (SNAT) based on the legacy L3
  implementation
* Support for centralized floating IP (DNAT) based on the legacy L3
  implementation
* Support for HA, in case the connection to the Controller is lost, fall back
  to the legacy L3 implementation until recovery. Reused all the legacy L3 HA.
  (Controller HA will be supported in the next release).
* Supports for centralized IPv6 based on the legacy L3 implementation

TODO
----

* Add support for North-South L3 IPv4 distribution (SNAT and DNAT)
* Add support for IPv6
* Support for multi controllers solution

Full description can be found in the project `Blueprints
<https://blueprints.launchpad.net/dragonflow>`_
