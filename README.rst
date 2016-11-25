========================
Team and repository tags
========================

.. image:: http://governance.openstack.org/badges/dragonflow.svg
    :target: http://governance.openstack.org/reference/tags/index.html

.. Change things from this point on

Distributed SDN-based Neutron Implementation

* Free software: Apache license
* Homepage:  http://launchpad.net/dragonflow
* Source: http://git.openstack.org/cgit/openstack/dragonflow
* Bugs: http://bugs.launchpad.net/dragonflow
* Documentation: http://docs.openstack.org/developer/dragonflow

.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/df_logo.png
    :alt: Solution Overview
    :width: 500
    :height: 350
    :align: center

Overview
--------

Dragonflow implements Neutron using a lightweight embedded SDN Controller.

Our project mission is *to Implement advanced networking services in a manner
that is efficient, elegant and resource-nimble*

Distributed Dragonflow
======================

Comprehensive agentless implementation of the Neutron APIs and advanced
network services, such as fully distributed Switching, Routing, DHCP
and more.

This configuration is the current focus of Dragonflow.
Overview and details are available in the `Distributed Dragonflow Section`_

.. _Distributed Dragonflow Section: http://docs.openstack.org/developer/dragonflow/distributed_dragonflow.html

.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/dragonflow_distributed_architecture.png
    :alt: Solution Overview
    :width: 600
    :height: 525
    :align: center

Mitaka Version Features
========================

* L2 core API

      IPv4, IPv6
      GRE/VxLAN/STT/Geneve tunneling protocols
      L2 Population

* Distributed L3 Virtual Router

* Distributed DHCP

* Distributed DNAT

* Security Groups Using OVS and Connection tracking

* Pluggable Distributed Database

      Supported databases:

      Stable:

          ETCD, RAMCloud, Redis, Zookeeper

      In progress:

            RethinkDB

* Pluggable Publish-Subscribe

         ZeroMQ, Redis

* Selective DB Distribution

    Tenant Based Selective data distribution to the compute nodes

Experimental Mitaka Features
=============================

    * Local Controller Reliability

In progress
============

  * IGMP Distributed application
  * Allowed Address Pairs
  * Port Security
  * DHCP DOS protection
  * Distributed Meta Data Service
  * Kuryr integration
  * Local Controller HA
  * ML2 Driver, hierarchical Port Binding
  * VLAN L2 Networking support
  * Smart broadcast/multicast

In planning
=============

  * Distributed Load Balancing (East/West)
  * DNS service
  * Port Fault detection
  * Dynamic service  chaining (service Injection)
  * SFC support
  * Distributed FWaaS
  * Distributed SNAT
  * VPNaaS

Configurations
==============

To generate the sample dragonflow configuration files, run the following
command from the top level of the dragonflow directory:

tox -e genconfig

If a 'tox' environment is unavailable, then you can run the following script
instead to generate the configuration files:

./tools/generate_config_file_samples.sh
