Distribute Load Balancer
========================
Include the URL of your launchpad RFE:

To be added.

This blueprint describe how to implement distributed load balancer in Dragonflow.


Problem Description
-------------------
Centralized load balancer have a weak point that is all load balancer traffic need go to centralized load balancer which will be bottleneck.

This blueprint intend to support the west-east L4 load balancer traffic to be handled in compute hosts without going to centralized load balancer node. And it will be implemented in one arm mode and in two arm mode.

Proposed Change
------------------
The following flow describes the changes needed in Dragonflow control plane and data plane in order to support distributed load balancer.

This spec will follow LBaaS V2 API, since LBaaS V1 API was removed in the Newton release.

Control plane

It will add a new LB plugin which handles all load balancer northbound API requests, and stores those requests into DF DB. This spec proposes adding new lb_app which is deployed at computer node. It has two responsibilities, one is getting API change from DF DB and configuring the right flow into br-int, the other one is monitoring the health status of local member and modifying the related flow of br-int. Its details working principle will be described in health monitor section.

Data plane

In order to implement load balancer functionality, this spec proposes adding a new table called load balancer table in which all load balancer flows will be built.

1.VIP ARP flow:
Add ARP responders for every VIPS, reply with VIP port MAC address. (This can be added in a designated table for ARP traffic while table 0 matches on ARP) Match only on traffic coming from VM,since this spec only will be limit in east west load balancer use cases.

2.In load balancer table, it uses group instruction with select mode to implement load balance algorithm.

3.Distribute load balancer is working in two mode,one is one arm mode,the other one is two arm mode.
  Mode 1: One arm mode.
  Case 1:VIP and member are in the same subnet, and client is also coming from the same subnet.
        1.1.The L2 lookup stage in the pipeline should match on the destination VIP MAC and send it to the load balancer table.
		1.2 If there is a established connection existed, then the packet will automatically get  DNATed
        to the same IP address as the first packet in that connection.
		1.3.1.In load balancer table, match metadata and VIP, action is to execute load balance algorithm to select one member,changing DST IP to member's IP address and change DST MAC to member's MAC address.
		1.3.2.Loading member's port key to reg7,and sending to egress table.
		1.4.Return traffic from member,it will change SRC IP address to VIP and change DST MAC to VIP MAC address, then send to load balancer table, it will do SNATed to client IP address,Lastly sending to ingress table.
  Case 2:VIP and member are in the same subnet, but client is coming from different subnet. since client and VIP are not in the same subnet, lb traffic will be forwarded by distributed router to VIP's subnet.
        2.1.The ingress dispatched table, should match on the destination VIP MAC and send it to the load balancer table.
		2.2.If there is a established connection existed, then the packet will automatically get  DNATed
        to the same IP address as the first packet in that connection.
		2.3.1.In load balancer table, match metadata and VIP, action is to execute load balance algorithm to select one member, then change DST IP to member's IP address and change DST MAC to member's MAC address.
		2.3.2.Loading member's port key to reg7, and sending to egress table.
		2.4.Return traffic from member,it will change SRC IP address to VIP and change DST MAC to VIP MAC address, then send to load balancer table, it will do SNATed to client IP address,Lastly sending to (ingress table-- because VIP and client are in different subnet???).


  Mode 2: Two arm mode.
  Case 1:VIP and member are in the different subnet,and client is also coming from the same subnet as VIP.
        1.1.The L2 lookup stage in the pipeline should match on the destination VIP MAC and send it to the load balancer table.
		1.2 If there is a established connection existed, then the packet will automatically get  DNATed
        to the same IP address as the first packet in that connection.
		1.3.1.In load balancer table, match metadata and VIP, action is to execute load balance algorithm to select one member,changing DST IP to member's IP address and change DST MAC to member's MAC address.
		1.3.2.Loading member's port key to reg7,and sending to egress table.
		1.4.Return traffic from member,it will change SRC IP address to VIP and change DST MAC to VIP MAC address, then send to load balancer table, it will do SNATed to client IP address,Lastly sending to ingress table.
  Case 2:VIP and member are in the different subnet,and client is also coming from the different subnet,since client and VIP are not in the same subnet, lb traffic will be forwarded by distributed router to VIP's subnet.
        3.1.The ingress dispatched table, should match on the destination VIP MAC and send it to the load balancer table.
		3.2 If there is a established connection existed, then the packet will automatically get  DNATed
        to the same IP address as the first packet in that connection.
		3.3.1.In load balancer table, match metadata and VIP, action is to execute load balance algorithm to select one member, then change DST IP to member's IP address and change DST MAC to member's MAC address.
		3.3.2.Loading member's port key to reg7, and sending to egress table.
		3.4.Return traffic from member,it will change SRC IP address to VIP and change DST MAC to VIP MAC address, then send to load balancer table, it will do SNATed to client IP address,Lastly sending to (ingress table-- because VIP and client are in different subnet???).



health monitor
  This spec proposes a distributed health monitor solution. It is composed of health monitor app and member health's status stored DB. health monitor app is dragonflow one which is located at every computer node. it is responsible of checking the status of any member which is located in the same computer node as health monitor. The checking result will be stored into DB, then this information will be propagated to health monitor app in other compute node.

  For a load balancer instance, health monitor app will send health monitor request by openflow packet_out message to all its members in the same compute node as health monitor app. health monitor response traffic need to be transfer to health monitor app to further handling.

  Since all traffic from member, it will change its SRC IP address to the related VIP IP address, and SRC MAC address to the related VIP MAC address. so in load balancer table, if both SRC and DST IP address are VIP IP address, this kind of traffic must be health monitor return traffic, it will be output to controller. The health monitor app located at controller will handle it.

  there should have a identification to let health monitor app know this health monitor traffic belongs to which load balancer.

  Health monitor app should change active member list according to member's feedback.

References

Please add any useful references here. You are not required to have any reference. Moreover, this specification should still make sense when your references are unavailable.
