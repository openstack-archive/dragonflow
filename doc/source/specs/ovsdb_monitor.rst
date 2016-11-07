..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

http://creativecommons.org/licenses/by/3.0/legalcode

=============
OVSDB Monitor
=============

This blueprint describe the addition of OVSDB monitor support for
Dragonflow. It implements the lightweight OVSDB driver which based
on the OVSDB monitor\notification mechanism, it solves the performance
problem for Dragonflow to fetch vm ports/interfaces info from OVSDB.

Problem Description
===================

In current Dragonflow implementation of fetch OVSDB data,
Dragonflow will start a loop to detect the add\update\delete for logical
ports, for example after Dragonflow finds a new logical port, it will
establish a socket channel to OVSDB, fetch many data from some OVSDB
tables(Bridge\Port\Interface Table) and find several useful
info(ofport\chassis id) for the new logical port. There are some
performance problems for above implementation:

The loop will consume many server resources because it will pull
large amount data from DB cluster and do the comparison with the
local cache frequently;

For each new logical port, Dragonflow will create a socket channel
to fetch data from OVSDB, if we create many new logical ports in the
future or even in a very short time, it will consume the server
resources further;

For each session between Dragonflow and OVSDB for a new logical port,
it will fetch many unnecessary data from many OVSDB tables;

Solution Description
====================

We bring in OVSDB monitor\notification mechanism which has detail
description in OVSDB protocol rfc
(https://tools.ietf.org/html/rfc7047#section-4.1.5)

We have Dragonflow and open vswitch on the same server, when OVS
start up, OVSDB will listen on port 6640, while when Dragonflow start
up, OVSDB driver will attempt to connect the OVSDB and subscribe the
data to OVSDB server which it is interested in, the details show below:

1. OVSDB server start up and listen on port 6640 and Dragonflow start
up while the OVSDB driver try to connect to OVSDB server as OVSDB
client with tcp:127.0.0.1:6640;

2. When OVSDB driver establish the channel with OVSDB server, OVSDB
driver send the OVSDB monitor command with below jsonrpc content:

method:monitor
params:[<db-name>,<json-value>,<monitor-requests>]
id:nonnull-json-value

In our solution, we only monitor the OVSDB "Interface Table",
so OVSDB driver will send the monitor Interface table jsonrpc
message to OVSDB server;

3. When OVSDB server receive the monitor message sent by OVSDB driver,
it will send a reply message which contains all the interfaces detail
info (if it has) back to OVSDB driver;

4. OVSDB driver receives and decodes the monitor reply message, it will
map each interface info to different type events(bridge online, vm online,
tunnel port online, patch port online), OVSDB driver will notify
these events to upper layer modules;

5. When tenant boot a vm on the host and add the vm port to the OVS bridge,
OVSDB server will send a notification to OVSDB driver according to the
update of OVS Interface Table, the notification will only contain the new
vm interface detail info, and after OVSDB driver receive the notification
it will do the same work as step 4;

6. When tenant shutdown a vm on the host and delete the vm port from the
OVS bridge, OVSDB server will send a notification to OVSDB driver according
to the update of OVS Interface Table, the notification will only contain
the delete vm interface detail info, and after OVSDB driver receive the
notification it will do the same work as step 4.

If we restart Dragonflow process or restart the OVSDB, Dragonflow OVSDB
driver will reconnect to OVSDB server, so step1 to 6 will be executed again.

Event Classification
====================

We could judge the event type according to the fields content in the
monitor reply or table change notification, if you want to see the
detail content in the message, you can execute the command on the
OVS(OVSDB monitor Interface -v) , the detail judgement fields show below:

Bridge online\offline:

type    internal
name    Br-int\br-tun\br-ex

Vm online\offline:

Iface-id   4aa64e21-d9d6-497e-bfa9-cf6dbb574054
name       tapxxx

Tunnel port online\offline:

Remote_ip    10.10.10.10
name         dfxxx
type         Vxlan\gre\geneve

Patch port online\offline:

type     patch
options  Peer=<peer port name>

Conclusion
==========
Our solution provides a lightweight OVSDB driver functionality which
implements the OVSDB data monitor and synchronize, remove the Dragonflow
loop process, maintain only one socket channel and transfer less data.
