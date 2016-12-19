Installation guide for Dragonflow
Keep in mind that Dragonflow is still in beta.

Prerequisites
-------------

1) Open vSwitch 2.5.0

Quick Installation
------------------

1) Clone Devstack

   ``git clone https://git.openstack.org/openstack-dev/devstack``

2) Copy one of the following as your ``local.conf`` to your devstack folder:

.. _DevStack Single Node Configuration: https://github.com/openstack/dragonflow/tree/master/doc/source/single-node-conf

.. _DevStack Multi Node Configuration: https://github.com/openstack/dragonflow/tree/master/doc/source/multi-node-conf

3) Edit local.conf according to your configuration, See `Detailed Installation`_ for more details, or the Devstack_ configuration manual

.. _Devstack: http://docs.openstack.org/developer/devstack/configuration.html


DHCP configuration (IPv4 Only Environment):
-------------------------------------------

   no configuration needed

DHCP configuration (mixed IPv4/IPv6 or pure IPv6):
--------------------------------------------------

   enable_service q-dhcp

   If the q-dhcp is installed on a different Node from the q-svc

   Please add the following flag to the neutron.conf on the q-svc node

   use_centralized_ipv6_DHCP=True

Meta data and cloud init
------------------------

In order to enable the VMs to get configuration like public keys,
hostnames, etc.. you need to enable meta service. You can do it
by adding the following lines to local.conf file (before running 
'stack.sh' command):

  enable_service q-meta
  enable_service q-dhcp

For the meta service to work correctly, another "hidden" service
must be started. It is called meta-service-proxy and it is
used to forward meta data client requests to real meta service.
By default, it is started by regular q-dhcp service for each tenant.
As a result 'q-meta' and 'q-dhcp' services must be enabled.
 
Database configuration:
-----------------------

Choose one of the following Database drivers in your local.conf

Etcd Database:

    enable_service df-etcd

    enable_service df-etcd-server

Ram Cloud Database:

    enable_service df-ramcloud

    enable_service df-rccoordinator

    enable_service df-rcmaster

Zookeeper Database:

    enable_service df-zookeeper

    enable_service df-zookeeper-server

Redis Database:

    enable_service df-redis

    enable_service df-redis-server


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


==========================================
Automated setup using Vagrant + Virtualbox
==========================================

`Vagrant Installation Guide <http://docs.openstack.org/developer/dragonflow/installation.html>`_

Troubleshooting
---------------
You can check northbound database  by using db-df utility, see details in
`Testing and Debugging <testing_and_debugging.rst>`_.
