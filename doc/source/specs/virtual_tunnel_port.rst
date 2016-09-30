..
   This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===========================
Virtual tunnel port support
===========================

https://blueprints.launchpad.net/dragonflow/+spec/virtual-tunnel-port-support

The virtual tunnel port can leave the remote_ip field of tunnel port to be
*flow*. And OpenFlow can designate remote_ip for tunnel port. So that every
node only needs to create a few tunnel ports for tunnel connection.

Problem Description
===================

Currently, Dragonflow node will create a tunnel port for every other Dragonflow
node in the in the OpenStack cloud. This has several problems in real use case.

* Every tunnel port will occupy one ofport in the bridge. Since Dragonflow
  doesn't have a dedicated bridge(like the br-tun in neutron) for tunnel port,
  the more Dragonflow nodes in the cloud, the less number of ofport will be
  available for use. Meanwhile, too many tunnel ports will increase the burden
  of OpenVSwitch DB.

* It is hard to maintain the tunnel ports in the Dragonflow node. When a
  Dragonflow node changes IP address, other Dragonflow nodes in the same
  cloud needs to update their tunnel ports. It has not been supported yet,
  and is being tracked in [#]_. Other Dragonflow nodes will need to query
  the tunnel port from OpenVSwitch DB, delete it and then create a new one.

.. [#] https://review.openstack.org/#/c/365077/

* Dragonflow only supports one type of tunnel underlay network one time.
  Multiple underlay tunnel type can be support, but that will aggravate
  the problems described above.

* Since one type of tunnel underlay network is supported one time, the
  multiple overlay network types, for example GRE, VXLAN, and Geneve, are
  using the same underlay network. This might cause problem, for example,
  the protocol overhead of GRE is 22, while the protocol overhead of Geneve
  is 30. User might see unexpected result when using Geneve as underlay
  network and GRE as overlay network.
  Besides, Dragonflow uses tunnel ID as identifier of different networks in
  OpenFlow. The tunnel ID is assigned by neutron. Different overlay tunnel
  network might have duplicated tunnel ID. This will cause match problem.
  For example, a GRE neutron network has tunnel ID 100, and a Geneve neutron
  network also has tunnel ID 100. In the underlay network, they will both use
  tunnel ID 100.

Proposed Change
===============

Create one virtual tunnel port for each supported tunnel types. So, no matter
how many Dragonflow nodes are there in the OpenStack cloud, each node will only
need to create and maitain several tunnel ports. These tunnel ports will be
created at the Dragonflow controller's first startup.

For example, the tunnel port will be:

::

    $ sudo ovs-vsctl show
    Bridge br-int
        Controller "tcp:127.0.0.1:6653"
        fail_mode: secure
        Port gre-tunnel-port
            Interface gre-tunnel-port
                type: gre
                options: {key=flow,local_ip=192.168.31.91,remote_ip=flow}
        Port br-int
            Interface br-int
                type: internal
    ovs_version: "2.5.0"

The supported tunnel types can be configured through configuration file. If
new tunnel type is added, the new tunnel port will be created when restart
Dragonflow controller. If a tunnel type is removed from the supported tunnel
types, the tunnel port will be deleted when restart Dragonflow controller.

The ofport of each tunnel type will be recorded as global variable across
the lifecyle of Dragonflow controller.

The tunnel_type field of chassis will be changed from a string to a list
of supported tunnel types.

The chassis will be added to local cache. So that a remote port can find the
chassis type and chassis IP address quickly.

A remote port might not be in current OpenStack cloud, but be in another
OpenStack cloud that connects to current cloud by using, for example,
L2 Gateway. If such a remote port is added, a *remote* chassis will be created
in local cache. The chassis id and IP will be the value of chassis field of the
remote port, which is the same as current implementation. The chassis
tunnel_type will be the type of the network of the remote port. A field called
hosted_ports will be added to such chassis in local cache. hosted_ports has the
ids of remote ports that are hosted by the *remote* chassis. Creating or
deleting remote port will change hosted_ports. If last remote port is deleted,
the *remote* chassis will be deleted from local cache.

The chassis update event from northbound DB will be notified to dragonflow
applications. So that the OpenFlow can be updated when chassis updates, for
example, its IP address.

In the egress table, the flow will be added based on the network type of
the network, where the port is in, and the remote port's chassis IP address.

In the ingress classification dispatch table, not only the tunnel ID will be
used to match the incoming request, but also the in_port will be used.
Different in_port means different tunnel types, so we can match network type
together with network segmentation ID.

Installed flows
---------------

The following flow is installed in the ingress classification dispatch table
for each tunnel network:

::

    match=tun_id:T,in_port:I actions=load:N->OXM_OF_METADATA[],resubmit(,INGRESS_DESTINATION_PORT_LOOKUP_TABLE)

Where T is the segmentation ID of the network, I is the ofport of virtual
tunnel port of the network type, and N is the local network ID of network in
current dragonflow controller.

The following flow is installed in the egress table for each remote port:

::

    match=reg7:R actions=load:T->NXM_NX_TUN_ID[],load:D->NXM_NX_TUN_IPV4_DST[],output:O

Where R is the tunnel key of logical port in dragonflow, T is the segmentation
ID of the network, D is the IP address of the destination chassis, O is the
ofport of virtual tunnel port of the network type.

Implementation
==============

Assignee(s)
-----------

Primary assignee:
  `xiaohhui <https://launchpad.net/~xiaohhui>`_

Work Items
----------

#. Add two configuration options. One is enable_virtual_tunnel_port. Its
   default value will be false for backward compatibility. The other one
   is tunnel_types, which is a list option. When enable_virtual_tunnel_port
   is true, a virtual tunnel port for each tunnel type in tunnel_types will
   be created.
#. Add chassis in local cache.
#. Add flows based on virtual tunnel port, chassis and network type.
#. Handle the chassis update event.
#. Remove the enable_virtual_tunnel_port and tunnel_type in configuration
   option. And remove all code for current implementation of tunnel port.
