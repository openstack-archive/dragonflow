Installation guide for Dragonflow
Keep in mind that Dragonflow is still in beta.

Prerequisites
------------

1) Devstack with Neutron ML2 as core plugin and OpenVSwitch 2.3.1 or newer.

Installation
-------------

1) Clone Devstack 

  - ``git clone https://git.openstack.org/openstack-dev/devstack``  

All changes needed to install Dragonflow are in devstack local.conf file.
You can find an example local.conf file in this directory.

2) Add the following lines to your local.conf

   ``enable_plugin dragonflow https://github.com/stackforge/dragonflow.git``
   ``Q_ENABLE_DRAGONFLOW=True``

   This adds and enable dragonflow as an external devstack plugin.
   Devstack stack.sh script has specific hooks that call the plugin at various stages.
   You can see what is installed as part of dragonflow in the dragonflow/devstack/plugin.sh file.

   ``ML2_L3_PLUGIN=dragonflow.neutron.services.l3.l3_controller_plugin.ControllerL3ServicePlugin``

   This line replaces the default L3 DVR service plugin with Dragonflow's implementation
   
3) In the ENABLED_SERVICES section (in local.conf), switch q-agt to q-df-agt and q-l3 to q-df-l3

   For example this:
   ``ENABLED_SERVICES+=,neutron,q-svc,q-agt,q-l3,q-dhcp,q-meta``

   Should be converted to this:
   ``ENABLED_SERVICES+=,neutron,q-svc,q-df-agt,q-df-l3,q-dhcp,q-meta``

   
4) Optionally add this in local.conf:

   ``Q_DF_CONTROLLER_IP='tcp:<your sdn controller ip>:6633'``

   This parameter is used by dragonflow's L3 Agent to start its SDN controller in the network node.
   By default this is set to be the same as your $HOST_IP 
   

Troubleshooting
----------------

