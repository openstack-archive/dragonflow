==========
Containers
==========

We belive that dragnflow can be also as networking backend for
containers.

Currently we create a poc for dragnflow as network-provider for
kuberenetes by implanting kuryr-kubernetes drivers that connected
update directly dragonflow northbound database.

the flowing openstack project that needed in POC:

  * kuryr - for all interaction with k8s that's include :
    api-server , cni and container network configuration.

  * ov-vif - for plug the pod port to ovs.

  * oslo-config - for configuration loading.

what not included in the POC:
(an hardcoded values supplied in the code)

  * IPAM

  * Mac allocation

  * Segmation allocation

  * ID's and naming of objects

  * Any k8s future except - pod to pod communication

How to install:
---------------

  * Run dev stack with kuryr_without_neutron.conf as local.conf

  * Update dargflow code with that patch and run: "pyton setup.py install"
    for intalling driver entry-point

  * update /etc/kuryr/kuryr.conf with the follwing lines :

    * pod_vif_driver = df-vif

    * pod_subnets_driver = df-subnets

    * pod_project_driver = df-project

    * pod_security_groups_driver = df-sg

  * run "sudo service devstack@kuryr-kubernetes restart"

  * install 2 pods by run "/usr/local/bin/kubectl apply -f
    https://k8s.io/docs/tasks/run-application/deployment.yaml"

  * check that pods are up - and  check ping between pods
