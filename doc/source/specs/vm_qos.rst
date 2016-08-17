..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===============
 VM Level QoS
===============

https://blueprints.launchpad.net/dragonflow/+spec/vm-qos

Problem Description
===================

The user would like to define a QoS policy of max/min bandwidth
per a VM instance which include all of the VM virtual NICs/ports.
This feature should work in conjunction with the Neutron QoS API [1]
which allows the user to define QoS policy per Neutron port, this should
still work after this design.

Proposed Change
===============

The following is the needed changes in the pipeline and data model in order
to support this feature:

Data model changes
-------------------
New table is added which holds QoS policy with min/max bandwidth and burst fields.
Another table is added to hold reference of VM instance id and QoS profile id.

On delete of a QoS profile id, all entries assigning VM's to this profile should
also be deleted (another option would be to block the profile deletion in case
it is in use)

Following the tables definitions:

CREATE TABLE qos_policy (
    policy_id        CHAR(256) NOT NULL PRIMARY KEY,
    max_kbps         INT(20)
    max_burst_kbps   INT(20)
);

CREATE TABLE vm_qos_policy (
    instance_id   CHAR(256) NOT NULL PRIMARY KEY,
    qos_policy_id CHAR(256)
);

Pipeline changes
-----------------

The following diagram depicts the packets flow for a VM with a QoS policy
assigned too, for illustration purposes the VM has 3 different virtual 
Neutron ports::

                                Apply QoS on eth-VM or on
                                eth-VM-loopback (rate limit or
           +---------+          queueing possible)
           |         |
           |   VM    |
           |         |
           +-+--+--+-+
             |  |  |             +---------->
             |  |  |             |          |
Ports 1,2,3  |  |  |             |          |
             |  |  |             |          |
             |  |  |           +-+-+      +-v-+
             |  |  |    eth-VM |   |      |   | eth-VM-loopback
           +-v--v+-v-------------+-+------+-+-+--------------------------------+
           |     |               |          |                                  |
           |     |               |          |                                  |
           |     |               |          v                                  |
           |     |               |                                             |
           |     +-------------->+          Convert packet mark to metadata    |
           |                                (network)                          |
           |                                and to reg6=port id                |
           |    mark packet                                                    |
           |    with port id                                                   |
           |    (1,2,3)                                                        |
           |    And send to                                                    |
           |    eth pair port                                                  |
           |    for this VM                                                    |
           |                                                                   |
           |                                                                   |
           +-------------------------------------------------------------------+

The following steps explains the pipeline:

1) When QoS policy is attached to a certain VM an eth-pair is created and looped
   back to OVS br-int. (eth-VM and eth-VM-loopback)

2) The classify flows on table 0 for ports 1,2 and 3 are converted to set packet
   mark to the port id and output to eth-VM port

3) QoS policy can be applied on eth-VM-loopback for rate limit or on
   eth-VM for queueing.

4) Add classify flows for table 0, inport=eth-VM-loopback and set metadata (network_id)
   and reg6=port_id according to packet mark (similar to original classify flows)

in order to implement this the following table is added::

         +----------------+      +----------+
         |                |      |          |
         |   Table 0      |      |  QoS     |
+-------->   Port         +----->+  Ingress +-----> Next table in pipeline
         |   classify     |      |          |
         |                |      |          |
         |                |      |          |
         +----------------+      +----------+

The QoS ingress table is empty by default
When a VM is attached to a certain QoS profile for the first time:

1) An eth pair connected as loop back on br-int is added with the instance id for the 
   pair port names (by QoS application) (port names eth-VM and eth-VM-loopback)

2) For all the VM local ports a flow is added to the QoS Ingress table:
   match: reg6=port_id => action: set packet_mark = port_id, output to eth-VM

3) Every time a local port is added/removed the QoS update the QoS Ingress table
   accordingly (see (2) for flows syntax)

4) Every flow on table 0 must go to the QoS Ingress table (change in L2 application)
   The default flow in QoS Ingress table is added to go to the next table
   in the pipeline.

5) QoS application adds a classifier flows for each VM local port on Table 0:
   match: in_port=eth-VM-loopback, pkt_mark=port_id => action: set reg6=port_id,
   metadata=network_id
   In this case needs to jump to the next table after QoS Ingress (Otherwise we
   will create a loop)      

6) QoS application must apply policy on either eth-VM or eth-VM-loopback ports of OVS


References
==========
[1] http://docs.openstack.org/mitaka/networking-guide/adv-config-qos.html
