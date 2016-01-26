..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

DragonFlow Benchmark Test Plan
==============================

This spec describe performance test of DragonFLow.

The spec includes testing scenarios, network link quality definition, testing methodology and testing tools.

Testing scenarios
=================
We would like benchmark DragonFlow performance in different scenarios:

- East-west performance testing
- Public network performance testing
- High load network traffic
- High go-to-control traffic
- Monday morning storm
- And more..

East-west performance testing
=============================
In this test we want to measure the network link quality in east-west traffic in different scenarios, both in single node and multi-node, combined with high number of flows handled by DF.

Environment setup
-----------------
* Create 100 vms/dockers on each node
* Create two new private networks
* Create a vm with iPerf client
* Create 4 vms with iPerf server:

1. Two VMs on same host as the client, on the two different networks
2. Two VMs on different  host than the client, on the two different networks

Tests description
-----------------
Generate 10 consequence tests with 5 seconds sleep between each test towards each server.
Run this test with different network encapsulation protocols:

- STT, GRE, VxLan, Geneve
- Run this test using Vlan tagging

Tests types
-----------
Measure Bandwidth and rate, Datagram loss, Jitter and Latency

Total number of tests
---------------------
4 x 5 x 4 = 80 tests

Public network performance testing
==================================
In this test we want to measure the public network link quality, download and upload scenario, combined with high number of flows handled by DF.

Environment setup
-----------------
Create 100 vms/dockers on single node

Create a vm with iPerf server with a floating IP

Test description & scenarios
----------------------------
Generate 10 consiquence tests with 5 seconds sleep between each test towards each server.

Upload to cloud scenario: Generate traffic towards the iPerf server

Download by cloud scenario: Run the same test in reverse mode (server sends, client receives)


Tests types
-----------
Measure Bandwidth and rate, Datagram loss, Jitter and Latency

Total number of tests
---------------------
2 x 4 = 8 tests

Testing methodology
===================
- For measuring DragonFlow networking improvement/overhead, all tests have to be executed with & without DF (with DVR. OVN as well?).
- The created VMs should report when there are up, so it will be possible to count the successfully created VMs in the automation.

Network link quality definition
===============================
The quality of a link can be tested as follows:

* Bandwidth - measured through iPerf TCP test
* Datagram loss - measured through iPerf UDP test. A good link quality: the packet loss should not go over 1%.
* Jitter (latency variation) - measured through iPerf UDP test
* Latency (response time or RTT) - measured using the Ping command

Tools & usage
=============
We will use iPerf for most of the tests. iPerf is a tool to measure the bandwidth and the quality of a network link.

Also we will use scripts that we will develop in order to automate the environment setup tests execution.

iPerf
=====
The network link is delimited by two hosts running iPerf. 

Bandwidth performance
---------------------
iperf -c Dest_IP

Bi-directional bandwidth
------------------------
iperf -c Dest_IP -r

Datagram loss & Jitter
----------------------
Client: iperf -c Dest_IP –u

Server: iperf -s -u -i 1 

Latency (Ping)
--------------
ping -c 10 -i 0.2 -w 3 DEST_IP

