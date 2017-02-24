..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

==============
VLAN aware VMs
==============

https://blueprints.launchpad.net/dragonflow/+spec/vlan-trunk

 There are various use cases where it would be useful to allow a VM
 to be attached to multiple networks using VLANs as a local
 encapsulation method.

Problem Description
===================

It is useful to allow a VM to different networks using a single port, and have
the VM dictate which traffic goes to which network. The use cases for this are:

* Some applications have requirements to connect to many (say, hundreds)
  of Neutron networks. It is more practical to use a single or other
  small number of VIFs and VLANs to differentiate traffic for each
  network than to have hundreds of VIFs per VM.

* Cloud workloads are often very dynamic. It may be more efficient and/or
  less complex to add/remove VLANs than to hotplug interfaces in a VM.

* A VM could be moved from one network to another without detaching
  the VIF from the VM.

* A VM may be running many containers. Each container may have
  requirements to be connected to different Neutron networks. Assigning
  a VLAN (or other encapsulation) id for each container is more efficient
  and scalable than requiring a vNIC per container.

* There are legacy applications that expect to use VLANs as a way to connect
  to multiple networks. Neutron should provide a way to expose that model
  to the VM decoupled from how the network is actually implemented.

This information is also available on the Neutron side [1]_.

Currently, this is not implemented in Dragonflow. A vlan-tagged packet is
treated like a regular packet, and passed as is.

Proposed Change
===============

Dragonflow will be notified by the API layer which ports are VLAN-tagged, to
which port they are attached, and what is their segmentation ID. The data
should be stored such that if new tagging methods (e.g. encapsulation, MPLS)
need to be added, there will be no change to the model and API layer.

In Dragonlfow, it is very easy to identify from which port and network a
packet is received.  This information is stored in OVS metadata by the
classification application. The network is stored in the metadata. The
destination port information is also stored in OVS metadata during
packet dispatch.

Data-Model Impact
-----------------

The Neutron API proposes two structures: `trunks` and `subports`.

`trunks` are only used to state that a port has subports, and acts as a
reference between subports and ports. We propose to do away with this object.

`subports` link two `port` objects. One is the parent port, which is connected
to the VM, and the second is a virtual port. Tagged packets should appear as
if they appear untagged from the virtual port.

We propose the following object: `TaggedPort`, with the following fields:

* `id` - The ID of the `TaggedPort`

* `version` - The version of the object (for versioning and consistency feature)

* `parent` - A reference to the parent port

* `port` - A reference to the virtual port

* `segmentataion_type` - The type of tagging used. Currently, only 'vlan' is
  supported.

* `segmentation_id` - The value of the tag used on this port.

API Impact
----------

Dragonflow will extend Neutron's TrunkPlugin service plugin [2]_.

It will implement the `add_subports` and `remove_subports` methods.

The `add_subports` method will create TaggedPort objects in the NB DB.

The `delete_subports` method will delete TaggedPort objects from the NB DB.

An endpoint will be added to `setup.cfg` to allow easy loading of the DF
VLAN aware VMs service plugin.

Local-Controller Impact
-----------------------

A VLAN-aware-VM application will be written, implementing the changes in this
section.

When a TaggedPort is created, a classification flow entry will be added
detecting packets tagged with the given type, and the tag value of the
given ID.

The classification flow will attach the relevant `reg6` and metadata `values`.

The classification flow will strip the VLAN tag.

The classification flow will have higher priority than the flows in the
classification app. If the type or tag do not match an existing TaggedPort,
it will fall back to the previous behaviour (the tag is ignored and passed
as-is)

For instance, let's assume that a parent port has id `0x166`, and ofport
`183`. It is connected to network `1`. There's also a `TaggedPort`
with segmentation type vlan and id `100`. Its ID is `0x168` and it's
connected to network `2`.

The following flows will be created:

::

  table=0, priority=150,in_port=183,vlan,vlan_tag=100 actions=strip_vlan,load:0x168->NXM_NX_REG6[],load:0x2->OXM_OF_METADATA[],resubmit(,5)
  table=0, priority=100,in_port=183 actions=load:0x166->NXM_NX_REG6[],load:0x1->OXM_OF_METADATA[],resubmit(,5)

When a TaggedPort is created, a dispatch flow will be created to match its
`reg7` value.

The dispatch flow will tag the packet, and send it to the parent port.

The flow will not conflict with classification app's dispatch flow, since they
match different `reg7` values.

For example, the same ports above will create the following flows.

::

  table=115, priority=100,reg7=0x168 actions=mod_vlan_vid:vlan_vid:0x10064,output:183
  table=115, priority=100,reg7=0x166 actions=output:183

Other Dragonflow applications will be updated to use port's unique key
(`reg6`/`reg7`) value, rather than relying on the `in_port`.

Devstack Impact
---------------

A new devstack option will exist to enable VLAN aware VMs.

This option will add the VLAN aware VMs application to the apps list.

This option will configure Neutron's config file to use Dragonflow's VLAN
aware VMs service plugin.

This option will be disabled by default. It can be enabled in local.conf.

Once the feature is stable, the option can be enabled by default.

Work Items
----------

* Change dragonflow apps to use unique key rather than in_port. Some apps are
  exempted, e.g. classification, tunneling, since these apps do need to work
  on the of-ports, rather than the Neutron logical ports.

  * port security

  * l3 (proactive and reactive)

  * dhcp

  * security groups

  * dnat

  * active_port_detection_app.py

  * metadata

* Implement data model

* Implement Neutron service plugin

* Implement VLAN aware VMs app

* Implement devstack changes

* Add fullstack tests

References
==========

.. [1] https://specs.openstack.org/openstack/neutron-specs/specs/newton/vlan-aware-vms.html

.. [2] https://review.openstack.org/#/c/320092/
