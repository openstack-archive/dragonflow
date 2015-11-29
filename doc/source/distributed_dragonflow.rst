=======================
Distributed Dragonflow
=======================

Dragonflow is a distributed SDN controller for OpenStack® Neutron™
supporting distributed Switching, Routing, DHCP and more.

Our project mission is to Implement advanced networking services in a
manner that is efficient, elegant and simple.

Designed to support large scale deployments with focus on latency and
performance.

Designed to introduce advanced innovative services locally on each compute
node, and with containers deployment in mind.

Dragonflow is a full Neutron implementation that is done the SDN way, our
motivation for creating yet another Neutron implementation:

1) We wanted to create an SDN implementation that is integral part of
   OpenStack, meaning both the plugin and the implementation are
   fully under OpenStack project and governance.

2) Dragonflow is fully open source and we welcome new contributors
   and partners to share a mutual vision.

3) We wanted Dragonflow to be VERY lightweight and simple in terms
   of size and code complexity, we want the entry point for new
   users/contributors to be very simple and fast.

4) Dragonflow is designed to support peformance intensive environments
   where latency is a big deal.

5) Dragonflow should be easily extensible

6) We believe in a distributed control plane


High Level Architecture
-----------------------

.. _Distributed Dragonflow Section: http://docs.openstack.org/developer/dragonflow/distributed_dragonflow.html

.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/dragonflow_distributed_architecture.png
    :alt: Solution Overview
    :width: 600
    :height: 525
    :align: center

Dragonflow environment consist of a local controller running at each of the
compute nodes in the setup.

These controllers all sync the network topology and policy using a pluggable
DB solution.
The controllers then map the policy into OpenFlow flows using the local
Dragonflow applications that communicate with the local OpenVSwitch.

The DB is being populated by Dragonflow Neutron plugin that converts neutron
API to our model.

The following sections each describe a specific topic/functionality in Dragonflow

Dragonflow Supported Features
=============================

Dragonflow Pipeline
===================

Dragonflow Pluggable DB
=======================

Distributed DHCP Application
============================

Containers and Dragonflow
=========================

Dragonflow Roadmap
==================
The following topics are areas we are examining for future features and
roadmap into Dragonflow project

- Containers
- Distributed SNAT/DNAT
- Reactive DB
- Topology Service Injection / Service Chaining
- Smart NICs
- Hierarchical Port Binding (SDN ToR)
- Inter Cloud Connectivity (Boarder Gateway / L2GW)
- Fault Detection
