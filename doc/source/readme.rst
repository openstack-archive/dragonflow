Installation guide for Dragonflow
Keep in mind that Dragonflow is still in beta.

Prerequisites
------------

1) Devstack with Neutron ML2 as core plugin and OpenVSwitch 2.3.1 or newer.

Quick Installation
-------------------

1) Clone Devstack 

   ``git clone https://git.openstack.org/openstack-dev/devstack``

2) Edit local.conf according to your configuration, See `Detailed Installation`_ for more details, or the Devstack_ configuration manual

.. _Devstack: http://docs.openstack.org/developer/devstack/configuration.html

3) Add the following lines in ``local.conf``:

::

   enable_plugin dragonflow https://github.com/stackforge/dragonflow.git

   Q_ENABLE_DRAGONFLOW=True

   ML2_L3_PLUGIN=dragonflow.neutron.services.l3.l3_controller_plugin.ControllerL3ServicePlugin

   Q_DF_CONTROLLER_IP='tcp:<your sdn controller ip>:6633' (Optinal, Default == $HOST_IP)

   Q_DF_DVR_BASE_MAC='base mac prefix to use for dvr routers' (Optional, Default == FA:16:3F:00:00:00)

In ENABLED_SERVICES section change q-agt to q-df-agt and q-l3 to q-df-l3

   ``ENABLED_SERVICES+=,neutron,q-svc,q-df-agt,q-df-l3,q-dhcp,q-meta``


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


Troubleshooting
----------------

