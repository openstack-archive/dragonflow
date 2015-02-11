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

Currently this project is available as a proof of concept (PoC) patch on top of Neutron.
We  are working  to make it available soon as a standalone agent.

Being the first release, support on the southbound interface is limited to Open vSwitch (OVS) with OpenFlow v1.3 stack (implemented using the RYU project, embedded in the Neutron L3 service plugin).

How to Install
--------------
here https://github.com/stackforge/dragonflow/tree/master/doc/source

Prerequisites
-------------
Install DevStack with Netron Ml2 as core plugin
Install OVS 2.3.1 or newer
Install Ryu (see "How to Install")

Features
--------

* APIs for routing IPv4 East-West traffic
* Performance improvement for inter-subnet network by removing the amount of kernel layers (namespaces and their TCP stack overhead)
* Scalability improvement for inter-subnet network by offloading L3 East-West routing from the Network Node to all Compute Nodes
* Reliability improvement for inter-subnet network by removal of Network Node from the East-West traffic
* Simplified virtual routing management
* Supports all type drivers GRE/Vxlan/VLAN

TODO
----

* Separate the Dragonflow virtual router from the L3 service plug-in, making it a stadnalone agent (will enable multi-controller scalability and decouple from Neutron project)
* Add support for North-South L3 IPv4 distribution (SNAT and DNAT)
* Remove change impact on Neutron L2 Agent by switching to OVSDB command for bootstrap sequence (set-controller and install arp responder)
* Add support for IPv6

