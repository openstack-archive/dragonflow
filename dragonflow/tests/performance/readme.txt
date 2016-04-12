OpenStack Neutron Data Plane Performance Testing Framework (aka Neutron-runner)
==============================================


Agenda
=================
	- Brief description
	- The configuration file
	- Setup the testing environment
	- Starting the tests
	- Get the tests results
	- Future work


Brief description
=================
This framework allows testing the data-plane performance and the network link quality of the different Neutron implantations, including DragonFlow, OVN, DVR, L3-Agent and others.
In the end of the process get summarized report with the tests results.

The testing framework consist from 3 components;
	1) Environment setup: used to the testing environment
	2) Tests execution: executes the different tests
	3) Reporting: summarize the data-plane performance and network link quality of tested network

	
Tests types
===========
The executed tests consists from network bandwidth tests and network link quality tests.
Tests type list:
	- Bandwidth (TCP)
	- Packets/second (ICMP)
	- Latency
	- Jitter
	
	* It's very easy to extend the performed test, e.g. add UDP bandwidth tests or add Packets/second for UDP, etc.


Tests scenarios
===========
The data plane performance is tested in different scenarios, both on same node and cross node:
	- East-west: L2 and L3
	- VM to floating IP (FIP)
	- Source NAT (SNAT)

	* The East-west is tested with different packet size: 2048, 1024, 512, 64 Bytes


The configuration file
=================
Before starting the environment setup and the tests itself, you have to edit the configuration file (configuration.conf).
You can edit the exiting file which contains sample data.
	- controllerNode: the hostname of controller node
	- computeNode: the hostname of compute node
	- CN_userName: username on the compute node (will be used for remote access using SSH)
	- CN_IP: the IP address of the compute node
	- numOfVMs: The number of VMs that will be used in parallel for testing the bandwidth
	- l2_subnet: The CIDR which will be created for L2 scenarios.
	- l3_subnet: The CIDR which will be created for L3 scenarios.
	- testTime: The test time duration (in seconds) for each test (I propose use at least 100).


Setup the testing environment
=================
	1) Before you start with the testing you have to setup a multinode OpenStack environment which consist from a controller node and a compute node.
	2) Copy the Neutron-runner to the control node and the enable_remote_command.sh file on the compute node.
	3) Change dir to the env_setup folder and run setup_environment.sh on the controller and follow the instructions.
	You are done :)

	* The setup_environment.sh can be run in different modes, you can start with: ./setup_environment.sh 0 1
	* It will upload to the compute node SSH keys, so it will be able to execute commands on the compute-node from remote. So just follow the instructions.


Starting the tests
=================
	- Run the start_perf_tests.sh from the root directory of the project and you are done :)
	- After the test complete, it will create locally a directory, named by current date and time, which contains the tests results and report.


Get the tests results
=================
	- Open using a browser the html file that located in the test results folder - timestamp/report/DP_results.html
	- You can also copy the folder (timestamp/report/) and open it on any other computer.


Future work
=================
	- Enrich project's documentation.
	- Add DNAT test scenario.
	- Add test that increase the MTU of CN to 9K and VMs to 54B less than 9K and run the all tests (probably will improvement the results).
	- Add another test with NetPerf for UDP PPS (currently the pps is measured by ICMP PPS).
	- Add another test with NetPerf for UDP performance tests.
	- Add abstraction layers:
		- Run the test with different local.conf and different tunnelling protocols.
		- Define which tests to run, which packet size for TCP iPerf.
	- Store historical test results.
	- Compare test results to specific test
	- Add another scenario: The third CN have 200 VMs (will cause to the OVS to hold many flows).
	- Support performance testing automation for CI.
	- Add scenarios for SecurityGroups (add 10 rules, 20 rules, ...).
	- Update the devstack and the Neutron implementation code on the compute node as well.
	- Run the tests in parallel of high network load on the entire cloud network.
	- Add OVS statistics and the hosts statistics to the report (use OVS-stats and env_setup/stats.sh).