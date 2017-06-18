..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

================================
Stand-alone Dragonflow L3 flavor
================================

Problem Description
===================

Dragonflow allows fully distributed L3 routing and source NATing. Those
features attracted some attention in the community it might be benefitial to
expose those independently of deploying Dragonflow as the main agent.

Proposed Change
===============

In a system where DF's local controller runs it does not make sense running an
L3 flavor separately, so in the context of this spec we'll only consider
deployments with other L2 agent types.

In those deployments, each compute node will have to run a DF flavored L3 agent
on top of an OVS bridge.

The system will have the following Dragonflow-related components:

* L3 router service provider

  Very similar to present day L3 router plugin

* L3 agent for each controll node

  An local-controller based service with a partial set of apps:

  * L3
  * NAT apps
  * Agent specific classification/dispatch - apps that capture L3 bound packets
    into agent's bridge, and returns them post routing back to the L2 agent.

* north-bound database and pub-sub
* partial ML2 mech driver

The last 2 points are agnostic and can be deployed in exactly the same manner.

References
==========

* L3 flavors

  https://specs.openstack.org/openstack/neutron-specs/specs/newton/multi-l3-backends.html

