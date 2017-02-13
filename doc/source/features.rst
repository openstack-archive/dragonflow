========
Features
========

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

  Distributed Metadata proxy application running locally at each
  compute node.

* DPDK

  Dragonflow shall work to support using OVS DPDK as the
  datapath alternative, this depends on the supported features
  in OVS DPDK and the VIF binding script support in Neutron
  plugin.

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
| HA Router extension *            | l3-ha                     | Done        |
+----------------------------------+---------------------------+-------------+
| L3 Agent Scheduler *             | l3_agent_scheduler        | Done        |
+----------------------------------+---------------------------+-------------+
| Neutron external network         | external-net              | Done        |
+----------------------------------+---------------------------+-------------+
| Neutron Extra DHCP opts          | extra_dhcp_opt            | Done        |
+----------------------------------+---------------------------+-------------+
| Neutron Extra Route              | extraroute                | Done        |
+----------------------------------+---------------------------+-------------+
| Neutron L3 Router                | router                    | Done        |
+----------------------------------+---------------------------+-------------+
| Network MTU                      | net-mtu                   | Done        |
+----------------------------------+---------------------------+-------------+
| Port Binding                     | binding                   | Done        |
+----------------------------------+---------------------------+-------------+
| Provider Network                 | provider                  | Done        |
+----------------------------------+---------------------------+-------------+
| Quality of Service               | qos                       | Done        |
+----------------------------------+---------------------------+-------------+
| Quota management support         | quotas                    | Done        |
+----------------------------------+---------------------------+-------------+
| RBAC Policies                    | rbac-policies             | Done        |
+----------------------------------+---------------------------+-------------+
| Security Group                   | security-group            | Done        |
+----------------------------------+---------------------------+-------------+
| Subnet Allocation                | subnet_allocation         | Done        |
+----------------------------------+---------------------------+-------------+
| Tap as a Service                 | taas                      | In Progress |
+----------------------------------+---------------------------+-------------+
| Service Function Chaining        | sfc                       | In Progress |
+----------------------------------+---------------------------+-------------+
| BGP dynamic routing              | bgp                       | In Progress |
+----------------------------------+---------------------------+-------------+
| Firewall service v2              | fwaas_v2                  | In Progress |
+----------------------------------+---------------------------+-------------+

(\*) Only applicable when conventional layer-3 agent enabled.
