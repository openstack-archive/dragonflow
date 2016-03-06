=========
Features
=========

Dragonflow offers the following virtual network services:

* Layer-2 (switching)

  Native implementation. Replaces the conventional Open vSwitch (OVS)
  agent.

* Layer-3 (routing)

  Native implementation or conventional layer-3 agent. The native
  implementation supports distributed routing.
  In the process of supporting distributed DNAT.
  SNAT is centralized at networking node.

* DHCP

  Distributed DHCP application that serves DHCP offers/acks locally at
  each compute node.

* Metadata

  Currently uses conventional metadata agent.
  In the process of creating distributed Metadata application.

* DPDK

  Dragonflow may be used with OVS using either the Linux kernel
  datapath or the DPDK datapath.

The following Neutron API extensions will be supported:

+----------------------------------+---------------------------+-------------+
| Extension Name                   | Extension Alias           |   TODO      |
+==================================+===========================+=============+
| agent                            | agent                     | Done        |
+----------------------------------+---------------------------+-------------+
| Auto Allocated Topology Services | auto-allocated-topology   | Done        |
+----------------------------------+---------------------------+-------------+
| Availability Zone                | availability_zone         | Done        |
+----------------------------------+---------------------------+-------------+
| DHCP Agent Scheduler             | dhcp_agent_scheduler      | Done        |
+----------------------------------+---------------------------+-------------+
| HA Router extension *            | l3-ha                     | Done        |
+----------------------------------+---------------------------+-------------+
| L3 Agent Scheduler *             | l3_agent_scheduler        | Done        |
+----------------------------------+---------------------------+-------------+
| Network Availability Zone        | network_availability_zone | In Process  |
+----------------------------------+---------------------------+-------------+
| Neutron external network         | external-net              | Done        |
+----------------------------------+---------------------------+-------------+
| Neutron Extra DHCP opts          | extra_dhcp_opt            | Done        |
+----------------------------------+---------------------------+-------------+
| Neutron Extra Route              | extraroute                | in Process  |
+----------------------------------+---------------------------+-------------+
| Neutron L3 Router                | router                    | Done        |
+----------------------------------+---------------------------+-------------+
| Network MTU                      | net-mtu                   | In Process  |
+----------------------------------+---------------------------+-------------+
| Port Binding                     | binding                   | Done        |
+----------------------------------+---------------------------+-------------+
| Provider Network                 | provider                  | In Process  |
+----------------------------------+---------------------------+-------------+
| Quality of Service               | qos                       | In Process  |
+----------------------------------+---------------------------+-------------+
| Quota management support         | quotas                    | Done        |
+----------------------------------+---------------------------+-------------+
| RBAC Policies                    | rbac-policies             | Done        |
+----------------------------------+---------------------------+-------------+
| security-group                   | security-group            | In Process  |
+----------------------------------+---------------------------+-------------+
| Subnet Allocation                | subnet_allocation         | Done        |
+----------------------------------+---------------------------+-------------+

(\*) Only applicable when conventional layer-3 agent enabled.