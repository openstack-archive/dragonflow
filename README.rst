Distributed SDN-based Neutron Implementation
.
* Free software: Apache license
* Homepage:  http://launchpad.net/dragonflow
* Source: http://git.openstack.org/cgit/openstack/dragonflow
* Bugs: http://bugs.launchpad.net/dragonflow
* Wiki: http://docs.openstack.org/developer/dragonflow

.. image:: https://raw.githubusercontent.com/openstack/dragonflow/master/doc/images/df_logo.png
    :alt: Solution Overview
    :width: 500
    :height: 350
    :align: center

Overview
--------

Dragonflow implements Neutron using a lightweight embedded SDN Controller.

Dragonflow is available in two configurations: Distributed and Centralized.

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


Centralized Dragonflow
======================

An implementation of a fully distributed virtual router, which replaces
DVR and can work with any ML2 mechanism and type drivers.

Overview and details are available in the `Centralized Dragonflow Section`_

.. _Centralized Dragonflow Section: http://docs.openstack.org/developer/dragonflow/centralized_dragonflow.html

