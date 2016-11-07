..
    This work is licensed under a Creative Commons Attribution 3.0 Unported
    License.

    http://creativecommons.org/licenses/by/3.0/legalcode

==============================================
DragonFlow Data Plane Performance Testing Spec
==============================================

This spec describes the data plane performance testing of DragonFLow.

The spec includes testing scenarios, network link quality definition, testing
methodology and testing tools and its usage.

Testing scenarios
=================
DragonFlow data plane performance benchmark in different scenarios:

- East-West data plane performance testing
- North-South data plane performance testing
- Source-NAT (SNAT) data plane performance testing
- High load network traffic
- High go-to-control traffic
- Monday morning storm
- And more..

East-West data plane performance testing
========================================
In this test we want to measure the network link quality in east-west traffic
in different scenarios, both in single node and multi-node, combined with high
number of flows handled by DragonFlow.

Environment setup
-----------------
1. Create two new private networks
2. Create 100 vms/dockers on each node
3. Create a vm with iPerf client
4. Create 4 vms with iPerf server:

 1. Same host traffic

  * L2 scenario
  * L3 scenario

 2. Cross host traffic

  * L2 scenario
  * L3 scenario

Tests description
-----------------
Generate 10 consequence tests with 5 seconds sleep between each test towards
each iPerf server.
Run this test with different network encapsulation protocols:

- STT, GRE, VxLan, Geneve
- Run this test using Vlan tagging

Tests types
-----------
Measure line Bandwidth, Datagram loss, Jitter and Latency.

Total number of tests
---------------------
4 x 5 x 4 = 80 tests

North-South data plane performance testing
==========================================
In this test we want to measure the North-South network link quality, combined
with high number of flows handled by DragonFlow controller.

Environment setup
-----------------
1. Create two new private networks
2. Create 100 vms/dockers on each node
3. Create a vm with iPerf client
4. Create 2 vms with iPerf server with a floating IP:

 * Same host as the iPerf client.
 * Cross host as the iPerf client.

Test description & scenarios
----------------------------
* Generate 10 consequence tests with 5 seconds sleep between each test towards
  the server.

Tests types
-----------
Measure Bandwidth and rate, Datagram loss, Jitter and Latency

Total number of tests
---------------------
2 x 4 = 8 tests

Source-NAT (SNAT) data plane performance testing
================================================
In this test we want to measure the SNAT (source network address translation)
network link quality, combined with high number of flows handled by DF.

Environment setup
-----------------
1. Create two new private networks
2. Create 100 vms/dockers on each node
3. Create 2 vms with iPerf client.
4. Run iPerf server on external IP

Test description & scenarios
----------------------------
* From each of the iPerf clients, generate 10 consequence tests with 5
  seconds sleep between each test towards the server.

Tests types
-----------
Measure Bandwidth and rate, Datagram loss, Jitter and Latency

Total number of tests
---------------------
2 x 4 = 8 tests

Testing methodology
===================
- For measuring DragonFlow networking improvement/overhead, all tests have to
  be executed with & without DF (with DVR. OVN as well?).
- The created VMs should report when there are up, so it will be possible to
  count the successfully created VMs in the automation.


Network link quality definition
===============================
The quality of a link can be tested as follows:

* Bandwidth - measured through iPerf TCP test
* Datagram loss - measured through iPerf UDP test. A good link quality: the
  packet loss should not go over 1%.
* Jitter (latency variation) - measured through iPerf UDP test
* Latency (response time or RTT) - measured using the Ping command

Tools & usage
=============
We will use iPerf for most of the tests. iPerf is a tool to measure the
bandwidth and the quality of a network link.

Also we will use scripts that we will develop in order to automate the
environment setup tests execution.

iPerf
=====
The network link is delimited by two hosts running iPerf.

Bandwidth performance
---------------------
iperf -c Dest_IP

Reverse mode bandwidth performance
----------------------------------
iperf -c Dest_IP -r

Datagram loss & Jitter
----------------------
Client: iperf -c Dest_IP -u

Server: iperf -s -u -i 1

Latency (Ping)
--------------
ping -c 10 -i 0.2 -w 3 DEST_IP

