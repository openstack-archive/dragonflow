Installation guide for Dragonflow
Keep in mind that Dragonflow is still in beta.

Prerequisites
------------

1) OVS 2.4.0

Quick Installation
-------------------

1) Clone Devstack

   ``git clone https://git.openstack.org/openstack-dev/devstack``

2) Edit local.conf according to your configuration, See `Detailed Installation`_ for more details, or the Devstack_ configuration manual

.. _Devstack: http://docs.openstack.org/developer/devstack/configuration.html

3) Add the following lines in ``local.conf``:

::

   Q_ENABLE_DRAGONFLOW_LOCAL_CONTROLLER=True

   enable_plugin dragonflow https://github.com/openstack/dragonflow.git

   enable_service df-controller

   enable_service db-ext-services

   enable_service q-svc

   enable_service q-l3

   enable_service q-dhcp

   disable_service q-agt
   disable_service n-net

Database configuration:
-------------------

Choose one of the following Database drivers in your local.conf

Etcd Database:

    enable_service df-etcd

    enable_service df-etcd-server

Ram Cloud Database

    enable_service df-ramcloud

    enable_service df-rccoordinator

    enable_service df-rcmaster

Detailed Installation
---------------------

Important parameters that needs to be set in ``local.conf`` :

::

    HOST_IP <- The management IP address of the current node
    FIXED_RANGE <- The overlay network address and mask
    FIXED_NETWORK_SIZE <- Size of the overlay network
    NETWORK_GATEWAY <- Default gateway for the overlay netowrk
    FLOATING_RANGE <- Network address and range for Floating IP addresses (in the public network)
    Q_FLOATING_ALLOCATION_POOL <- range to allow allocation of floating IP from (within FLOATING_RANGE)
    PUBLIC_NETWORK_GATEWAY <- Default gateway for the public network
    SERVICE_HOST <- Management IP address of the controller node
    MYSQL_HOST <- Management IP address of the controller node
    RABBIT_HOST <- Management IP address of the controller node
    GLANCE_HOSTPORT <- Management IP address of the controller node (Leave the port as-is)

You can find example configuration files in the multi-node-conf or the single-node-conf directories.


============================================
 Automated setup using Vagrant + Virtualbox
============================================

`Vagrant Installation Guide <https://github.com/openstack/dragonflow/tree/master/doc/source/installation.rst>`_

Troubleshooting
----------------
