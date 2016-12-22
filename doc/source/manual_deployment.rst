..
      Copyright (c) 2016 OpenStack Foundation

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Dragonflow Manual Deployment
============================

Dragonflow mainly has several components:

#. Dragonflow neutron plugins (set up in neutron-server configuration)
#. Dragonflow local controller running on each compute node
#. Dragonflow metadata service running on each compute node
#. Dragonflow publisher service running aside neutron server (if zeromq pub/sub driver is enabled)
#. Dragonflow l3 agent running on each network node
#. Dragonflow northbound database (depends on which database you set up in dragonflow configuration)

Source Code
-----------

https://github.com/openstack/dragonflow

Dependencies
------------

#. Open vSwitch 2.5+
#. Northbound Database (Etcd or Zookeeper or Redis)

Basic Configurations
--------------------

#. Generate the plugin configuration

::

   bash tools/generate_config_file_samples.sh
   cp etc/dragonflow.ini.sample /etc/neutron/dragonflow.ini

#. Modify the configuration

/etc/neutron/neutron.conf
~~~~~~~~~~~~~~~~~~~~~~~~~

::

    [DEFAULT]
    metadata_proxy_shared_secret = secret
    dhcp_agent_notification = False
    notify_nova_on_port_data_changes = True
    notify_nova_on_port_status_changes = True
    allow_overlapping_ips = True
    service_plugins = df-l3,qos
    core_plugin = neutron.plugins.ml2.plugin.Ml2Plugin

    [qos]
    notification_drivers = df_notification_driver

/etc/neutron/plugins/ml2/ml2_conf.ini
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    [ml2]
    tenant_network_types = geneve
    extension_drivers = port_security,qos
    mechanism_drivers = df

    [ml2_type_flat]
    flat_networks = *

    [ml2_type_geneve]
    vni_ranges = 1:10000

/etc/nova/nova.conf
~~~~~~~~~~~~~~~~~~~

::

    [neutron]
    service_metadata_proxy = True
    metadata_proxy_shared_secret = secret

/etc/neutron/plugins/dragonflow.ini
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    [df]
    metadata_interface = tap-metadata
    enable_selective_topology_distribution = True
    apps_list = l2_app.L2App,l3_proactive_app.L3ProactiveApp,dhcp_app.DHCPApp,dnat_app.DNATApp,sg_app.SGApp,portsec_app.PortSecApp,portqos_app.PortQosApp
    integration_bridge = br-int
    tunnel_type = geneve

    [df_dnat_app]
    ex_peer_patch_port = patch-int
    int_peer_patch_port = patch-ex
    external_network_bridge = br-ex

    [df_l2_app]
    l2_responder = True

    [df_metadata]
    port = 18080
    ip = 169.254.169.254

Northbound Database
-------------------

Dragonflow supports etcd, redis, zookeeper and ramcloud. You need to deploy one of them
in your environment and expose the necessary TCP port.

Next you need to change the configuration, for example, etcd:

/etc/neutron/plugins/dragonflow.ini:

::

    [df]
    nb_db_class = etcd_nb_db_driver
    remote_db_port = {etcd_port}
    remote_db_ip = {etcd_ip}

Pub/Sub Driver
--------------

Dragonflow supports zeromq and redis. You need to change the configuration, for example, zeromq:

/etc/neutron/plugins/dragonflow.ini:

::

    [df]
    enable_df_pub_sub = True
    pub_sub_driver = zmq_pubsub_driver
    publisher_multiproc_socket = /var/run/zmq_pubsub/zmq-publisher-socket
    pub_sub_multiproc_driver = zmq_pubsub_multiproc_driver
    pub_sub_use_multiproc = True
    publisher_rate_limit_count = 1
    publisher_rate_limit_timeout = 180
    monitor_table_poll_time = 30

Dragonflow Plugin (on neutron-server node)
------------------------------------------

Installation
~~~~~~~~~~~~

#. Install dragonflow dependencies: pip install -r requirements.txt
#. Install dragonflow: python setup.py install

Service Start
~~~~~~~~~~~~~

neutron-server is the only service for this part.

Dragonflow Publisher Service (on neutron-server node)
-----------------------------------------------------

Installation
~~~~~~~~~~~~

::

    mkdir -p /var/run/zmq_pubsub
    chown -R neutron:neutron /var/run/zmq_pubsub

Service Start
~~~~~~~~~~~~~

::

    python /usr/local/bin/df-publisher-service --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/dragonflow.ini

Dragonflow local controller (on compute node)
---------------------------------------------

Installation
~~~~~~~~~~~~

#. Install dragonflow dependencies: pip install -r requirements.txt
#. Install dragonflow: python setup.py install
#. Initialize ZeroMQ:
   ::

       mkdir -p /var/run/zmq_pubsub
       chown -R neutron:neutron /var/run/zmq_pubsub

#. Initialize OVS:
   ::

       ovs-vsctl add-br br-ex
       ovs-vsctl add-port br-ex {external_nic}
       ovs-vsctl add-br br-int
       ovs-vsctl add-port br-int {internal_nic}
       ovs-vsctl --no-wait set bridge br-int fail-mode=secure other-config:disable-in-band=true
       ovs-vsctl set bridge br-int protocols=OpenFlow10,OpenFlow13
       ovs-vsctl set-manager ptcp:6640:0.0.0.0

Configuration
~~~~~~~~~~~~~

/etc/neutron/dragonflow.ini:

::

    [df]
    local_ip = {compute_node_ip}

Service Start
~~~~~~~~~~~~~

::

     python /usr/local/bin/df-local-controller --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/dragonflow.ini

Dragonflow Metadata Service (on compute node)
---------------------------------------------

Service Start
~~~~~~~~~~~~~

::

    python /usr/local/bin/df-metadata-service --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/dragonflow.ini

Dragonflow L3 Service (on network node)
---------------------------------------

Installation
~~~~~~~~~~~~

#. Install dragonflow dependencies: pip install -r requirements.txt
#. Install dragonflow: python setup.py install

Configuration
~~~~~~~~~~~~~

/etc/neutron/l3_agent.ini:

::

    [DEFAULT]
    external_network_bridge =
    interface_driver = openvswitch
    ovs_use_veth = False

Service Start
~~~~~~~~~~~~~

::

    python /usr/local/bin/df-l3-agent --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/l3_agent.ini --config-file /etc/neutron/dragonflow.ini
