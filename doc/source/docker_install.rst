Building the image
------------------
* Run the following command

.. code-block:: bash

  docker build --tag dragonflow .


Running the image
-----------------

Preparation work
~~~~~~~~~~~~~~~~
* Create a network to be used by the containers

.. code-block:: bash

  docker network create --subnet=172.18.0.0/16 dragonflow_net

Running etcd node
~~~~~~~~~~~~~~~~~
* Run the following commands:

.. code-block:: bash

  mkdir -p /tmp/etcd
  chcon -Rt svirt_sandbox_file_t /tmp/etcd
  export NODE1=172.18.0.2
  export DATA_DIR=/tmp/etcd
  docker run --detach -p 2379:2379 -p 2380:2380 --net dragonflow_net --ip ${NODE1} --volume=${DATA_DIR}:/etcd-data --name etcd quay.io/coreos/etcd:latest /usr/local/bin/etcd --data-dir=/etcd-data --name node1 --initial-advertise-peer-urls http://${NODE1}:2380 --listen-peer-urls http://${NODE1}:2380 --advertise-client-urls http://${NODE1}:2379 --listen-client-urls http://${NODE1}:2379 --initial-cluster node1=http://${NODE1}:2380


* Make sure the IP was properly assigned to the container:

.. code-block:: bash

  docker inspect --format '{{ .NetworkSettings.IPAddress }}' etcd

Running controller node
~~~~~~~~~~~~~~~~~~~~~~~
* Run the following commands:

.. code-block:: bash

  export DRAGONFLOW_ADDRESS=172.18.0.3
  docker run --name dragonflow --net dragonflow_net --ip ${DRAGONFLOW_ADDRESS} dragonflow:latest --dragonflow_address ${DRAGONFLOW_ADDRESS} --db_address ${NODE1}:2379

* Make sure the IP was properly assigned to the container:

.. code-block:: bash

  docker inspect --format '{{ .NetworkSettings.IPAddress }}' dragonflow

