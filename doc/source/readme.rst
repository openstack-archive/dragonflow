Note Currently in the PoC implementation the SDN controller is embedded into the L3 service plugin so there is no need to run/ deploy the L3 Agent.

Prerequisite
------------
1) Clone the devstack into the controller node and into all the compute nodes

  ``cd /opt/stack``

  ``git clone https://git.openstack.org/openstack-dev/devstack``

 -  Install multi node devstack instalation using Neutron ML2 core plugin

 -  Here's a sample devstack multi-node installation configuration file

2) Git-Checkout the last merged label

  ``cd /opt/stack/neutron/``

  ``git checkout 51a6260266dc59c066072ca890ad9c40b1aad6cf``

3) Apply the L3 controller patch

  -  Download from this folder

  ``git apply --whitespace=nowarn l3_controller.patch``

Setup
-----

1) Enable the Controller L3 service plugin

  -  Make the following changes in ``neutron.conf``:

    -  Comment-out loading of the ``L3RouterPlugin``
    -  Add the ``neutron.services.l3_router.l3_cont_dvr_plugin.ControllerL3ServicePlugin`` to the service plugin list

  **neutron.conf**

  ``[default]``

    ``#service_plugins =neutron.services.l3_router.l3_router_plugin.L3RouterPlugin``

    ``service_plugins=neutron.services.l3_router.l3_cont_dvr_plugin.ControllerL3ServicePlugin``

  -  Make the following change in ``ml2_conf.ini``:

    - Enable the L3 Controller

  **ml2_conf.ini**

    ``[agent]``

    ``enable_l3_controller = True``

 2. Remove deployment of L3 Agent or DVR Agent from the Network Node (make sure the L3 Agent is not running)

**Note: This will disable north-south traffic, allowing you only to test east-west**

`(TODO) explain how to remove L3/DVR Agent`

 3. Installing Ryu on Controller Node

  -  Cloning the Ryu project

  ``git clone git://github.com/osrg/ryu.git``

  -  Apply the folowing change to enable Ryu to run in Library mode (instead of a standalone controller) 

   Replace   `register_cli_opts`  to `register_opts` in the following files:

    ``ryu/controller/controller.py``

    ``ryu/app/wsgi.py``

Run the following commands:
 ``sed -i 's/register_cli_opts/register_opts/g' ryu/controller/controller.py``

 ``sed -i 's/register_cli_opts/register_opts/g' ryu/app/wsgi.py``



 ``% cd ryu;     python ./setup.py installl``
