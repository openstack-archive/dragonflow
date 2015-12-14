Security Group

https://blueprints.launchpad.net/dragonflow/+spec/security-group-dragonflow-driver 
This blueprint describe how to implement Security Group in Dragonflow.

1	Problem Description
Neutron use iptables to implement security group in current community solution. Because connect tracking is not supported by ovs, one linux bridge is inserted between VM and ovs bridge. However, it introduces unnecessary overhead and latency for traffic forwarding. 

As connection tracking is supported in ovs v2.4.0 now, seurity group iptables rules can be translated into openflow tables and installed in ovs bridge to implement traffic security control.

This blueprint intends to support security group directly in ovs bridge only using flow tables without iptables and corresponding linux bridges. It can improve forwarding efficiency due to packets only go through the network stack once. The traffic in iptables solution need go through the network stack twice (including linux bridge and ovs bridge). 

2	Proposed Change
The following flow describe the changes needed in Dragonflow pipeline in order to support security groups.
Dragonflow controller will create extra three security group tables for Dragonflow pipeline to make security group functional: ingress security, forwarding security and egress security.

2.1	Setup
For blueprint solution, nova should not create linux bridge and plug port directly into integrity bridge.

2.2	Configuration - Security Group Added
Security Group is configured in the Neutron DB and Dragonflow plugin map this configuration to Dragonflow's DB model and populate security group table.
Each controller must detect if the Security Group is assigned to a local port and in the case that it is, install the relevant flows for ingress, egress and forwarding security tables as described below.

2.3	Ingress Security Table
This section describes all the handling in the pipeline for traffic coming from a vm port. When traffic leaves vm port, as soon as it matches ingress classification table (Table 0) and before it enters the service traffic table, it enters into ingress security group table. 
Ingress security group table provides following features as below, and the flows installed in this table are all proactive way.
1)Anti-arp ip spoofing
  When controller has detected the Security Group is assigned to a local port, it install this flow. This flow matches the in_port and the port's mac and ip pair and passes it to the next table. If doesnot match, it drops the packet.
2)Anti-dhcp spoofing
  A vm is never being expected to be a dhcp server, thus must not send dhcp reply messages. In case of it, the controller will install a flow which drops all the dhcp server packets from a vm port, matching fields includeing protocol:udp, scr port:67 and dst port:68. 

2.4	Forwading Security Table
This section describe all the handling in the pipeline for traffic forwarding. When traffic leaves Packet Classifier Table and before it goes into L3 forwarding table, it enters into forwarding security group table. 
The procedures are detailed below, and the flows mentioned in this section are reactive way.
	The forwarding security table is empty at beginning; it means all packets coming into this table will pack into the controller. 
	Dragonflow controller inspects the security rules corresponding to the packet's key words. For example, the dst ip, the protocol, the tcp upd port number. If controller decides to forward such packet, it will install a flow into the integrity bridge to let this packet go to the next table for further processing. At reverse, it will install a drop flow matching this packet. As a result, such packet will be discarded. 
	Because ovs already supports connect tracking, the controller will install a flow matching the corresponding state to let such packet pass.

2.5	Egress Security Table
This section describes all the handling in the pipeline for Egress traffic. 
Egress defaults to pass all traffic since there are no requirements for egresss security table.

3	References
https://github.com/justinpettit/ovs/tree/conntrack
https://lwn.net/Articles/652967/
http://openvswitch.org/support/ovscon2014/17/1030-conntrack_nat.pdf





