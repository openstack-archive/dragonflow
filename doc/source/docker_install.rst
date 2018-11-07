==============
DOCKER INSTALL
==============

Building the image
------------------
* Run the following command

.. code-block:: bash

  docker build --tag dragonflow .


Running the image
-----------------

Preparation work
~~~~~~~~~~~~~~~~
* Create a network to be used by the containers, use any subnet you find fit,
  the subnet here is just an example.

.. code-block:: bash

  export DRAGONFLOW_NET_NAME=dragonflow_net
  docker network create --subnet=172.18.0.0/16 $DRAGONFLOW_NET_NAME

Running etcd node
~~~~~~~~~~~~~~~~~
* Run the following commands:

.. code-block:: bash

  mkdir -p /tmp/etcd
  chcon -Rt svirt_sandbox_file_t /tmp/etcd
  export NODE1=172.18.0.2 # Any free IP in the subnet
  export DATA_DIR=/tmp/etcd
  docker run --detach --net $DRAGONFLOW_NET_NAME --ip ${NODE1} --volume=${DATA_DIR}:/etcd-data --name etcd quay.io/coreos/etcd:latest /usr/local/bin/etcd --data-dir=/etcd-data --name node1 --initial-advertise-peer-urls http://${NODE1}:2380 --listen-peer-urls http://${NODE1}:2380 --advertise-client-urls http://${NODE1}:2379 --listen-client-urls http://${NODE1}:2379 --initial-cluster node1=http://${NODE1}:2380


* Make sure the IP was properly assigned to the container:

.. code-block:: bash

  docker inspect --format "{{ .NetworkSettings.Networks.${DRAGONFLOW_NET_NAME}.IPAddress }}" etcd


Running controller node
~~~~~~~~~~~~~~~~~~~~~~~
This section assumes you have OVS set up. Make sure ovsdb-server listens on
TCP port 6640. This can be done with the following command. Note you may need
to allow this via `selinux`.

.. code-block:: bash

  sudo ovs-appctl -t ovsdb-server ovsdb-server/add-remote ptcp:6640

* Run the following commands:

.. code-block:: bash

  export DRAGONFLOW_IP=172.18.0.3 # Any free IP in the subnet
  export MANAGEMENT_IP=$(docker inspect --format "{{ .NetworkSettings.Networks.${DRAGONFLOW_NET_NAME}.Gateway }}" etcd)  # Assuming you put OVS on the host
  docker run --name dragonflow --net $DRAGONFLOW_NET_NAME --ip ${DRAGONFLOW_IP} dragonflow:latest --dragonflow_ip ${DRAGONFLOW_IP} --db_ip ${NODE1}:2379 --management_ip ${MANAGEMENT_IP}

* Make sure the IP was properly assigned to the container:

.. code-block:: bash

  docker inspect --format "{{ .NetworkSettings.Networks.${DRAGONFLOW_NET_NAME}.IPAddress }}" dragonflow

There are two configuration files that Dragonflow needs, and creates
automatically if they do not exist:

* `/etc/dragonflow/dragonflow.ini`

* `/etc/dragonflow//etc/dragonflow/dragonflow_datapath_layout.yaml`

If these files exist, they are used as-is, and are not overwritten. You can add
these files using e.g.
`-v local-dragonflow-conf.ini:/etc/dragonflow/dragonflow.ini`.



Running the container without the controller service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The docker entrypoint accepts verbs. To start the container without the
controller service, use the verb `bash`.

.. code-block:: bash

  docker run --name dragonflow --net $DRAGONFLOW_NET_NAME --ip ${DRAGONFLOW_ADDRESS} -i -t dragonflow:latest --dragonflow_address ${DRAGONFLOW_ADDRESS} --db_address ${NODE1}:2379 bash

This enables you to run the container without running the container service.
This is useful in order to create a standalone node for Dragonflow API,
separated from the controller node.

Running a REST API Service
~~~~~~~~~~~~~~~~~~~~~~~~~~

To start a REST API service, running on HTTP port 8080, use the verb `rest`.

.. code-block:: bash

  docker run --name dragonflow --net $DRAGONFLOW_NET_NAME --ip ${DRAGONFLOW_ADDRESS} -i -t dragonflow:latest --dragonflow_address ${DRAGONFLOW_ADDRESS} --db_address ${NODE1}:2379 rest

The schema would be available on `http://$DRAGONFLOW_ADDRESS:8080/schema.json`.
