..
 This work is licensed under a Creative Commons Attribution 3.0 Unsuported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=======================================
Communication Across Multiple OpenStack
=======================================

This spec proposes the solutions of Communication across multiple OpenStack
for Dragonflow.

Problem Description
===================

In the large scale deployment situation, we will deploy a large number of
compute nodes. However, the management ability of one OpenStack system is
limited, when the number of compute nodes is large enough, the ability of
DF DB and the performance of sub/pub process become a big problem.

So we must divide the many compute nodes into different regions, each region
is managed by one OpenStack which has the independent DF DB and sub/pub
system. We could introduce a higher level Orchestrator to manage the multiple
OpenStack regions.

If two virtual machines which belong to the same network are divided into
different OpenStack Region, we must resolve the communication problem between
the two virtual machines.

Proposed Change
===============

To resolve the problem, the general idea is Neutron plugin analyses the
notification message which indicates a remote Neutron port has been created
sent by the Orchestrator layer and finds it's a remote Neutron port which
comes from another OpenStack region, plugin will assign a specific chassis
name for the port and publish the message. The corresponding chassis will
receive the message because of its previously subscribe, and it will create
corresponding tunnel port to the remote chassis which contains the remote
Neutron port and install the forwarding rules.

Neutron Plugin
--------------

When a remote Neutron port which belongs to a VM is created in remote
OpenStack region, the Orchestrator layer will send a create_port notification
message to local OpenStack region, and Local Neutron plugin will process it,
the details show below:

1. We could assume the binding_profile field contains the info that indicate
the Neutron port is a remote port comes from another OpenStack region, the
field could be like this:

binding_profile = {"port_key": "remote_port",
                   "host_ip": remote_chassis_ip}

2. When Neutron plugin find it is a remote port by the binding_profile field
in the create_port message, it will generate a specific chassis name for the
remote port, store the lport in DF DB and publish the create_port message,
the chassis name could be like this:

chassis_name = "RemoteChassis:remote_chassis_ip"

DF Local Controller
-------------------

The corresponding chassis will receive the create_port message published by
Neutron plugin because of its previously subscribe:

1. DF local controller will analyse the create_port message and find it is a
remote OpenStack region port by the specific chassis name, and also it will
fetch the remote tunnel ip by the chassis name.

2. Local controller will check whether the chassis has the tunnel port from
itself to the specific remote chassis, if not, it will create the tunnel
port and establish the tunnel to the remote chassis.

3. After the tunnel port has been created, local controller will notify the
create_lport message to Apps, it will be considered a normal remote port as
in current implementation.

On the other hand, when the last remote OpenStack region port on a remote
chassis would be deleted from local cache, it means there are no need to
communicate to the remote chassis anymore for the local controller, it should
delete the corresponding tunnel port.
