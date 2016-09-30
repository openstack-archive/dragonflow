..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===========================
Remote Device Communication
===========================

https://blueprints.launchpad.net/dragonflow/+spec/remote-device-communication

This spec proposes the solution of communicating to a remote device which
is not managed by Dragonflow.

Problem Description
===================

In the common scenario, a VM not only needs to communicate with another VM
but also a physical machine, however, the virtual or physical machine
may not be managed by Dragonflow, in this spec we call them remote device,
if a VM in Dragonflow wants to communicate to remote device, Dragonflow
needs to know some info of the remote device.

Usually we would deploy a VTEP for virtual or physical machine in DC network,
such as the Openvswitch vxlan port, the VTEP TOR(top of rack) and the
physical router which support VTEP, so if Dragonflow knows the correct VTEP
IP, VM in Dragonflow could access remote device by the overlay network.

The remote device may belong to one tenant or it has no tenant info at all.
It could be managed by another cloud OS and how the remote device knows the
location of the VM in Dragonflow and accesses it is out of the scope of this
spec.

Proposed Change
===============

To resolve the problem, the general idea is we should tell the info of remote
device to Dragonflow. We can invoke the Neutron API create_port and provide
the info of remote device, plugin will assign a specific chassis name for
the remote device and publish the create_port message. After the chassis
receives the message, it will create corresponding tunnel port to the remote
chassis and install the forwarding rules.

Neutron Plugin
--------------

When we invoke the create_port Neutron API provided by Neutron plugin in
Dragonflow, it will process it:

1. We put the info that indicates the Neutron port is a remote device port
into the binding_profile field so that Neutron plugin could recognize it:

binding_profile = {"port_key": "remote_port",
                   "host_ip": remote_chassis_ip}

2. When the Neutron plugin finds it is a remote port by the binding_profile
field in the create_port message, it will assign the remote_chassis_ip as
the chassis name of the remote port, because the remote_chassis_ip should be
unique in DC network. Then it will store the lport in DF DB and publish the
message with corresponding topic, if the lport belongs to some tenant, we
could use tenant_id as the topic.

DF Local Controller
-------------------

DF local controller will process above notification message:

1. DF local controller will analyse the create_port message and find it is a
remote device port by the specific chassis name, and also it will fetch
the remote tunnel ip by the chassis name.

2. Local controller will check whether local chassis has the tunnel port from
itself to the specific remote chassis, if not, it will create the tunnel
port and establish the tunnel to the remote chassis.

3. After the tunnel port has been created, local controller will notify the
create_lport message to Apps, it will be considered a normal remote port as
in current implementation.

On the other hand, when the remote device port is deleted from local cache,
it means there are no need to communicate to the remote chassis anymore
for the local controller, it should delete the corresponding tunnel port and
forwarding rules.
