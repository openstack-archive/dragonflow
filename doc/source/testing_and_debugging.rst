=====================
Testing and Debugging
=====================

This page discusses the testing and debugging capabilities that come
with dragonflow.

Testing
=======

After installing with devstack, there are a few tests that can be ran
to verify Dragonflow was installed correctly.

Fullstack tests
---------------

The fullstack tests execute Neutron API commands, and then verifies the
pipeline. This is done by creating relevant ports, simulating a plug-vif
event, and then passing packets on these ports. The tests verify that
packets are received if and only if they are supposed to, and that any
necessary modification is done, e.g. replacing L2 addresses in L3 routing.

To run the tests:

::

    > tox -e fullstack

Debugging
=========

There are a few tools that exist to debug Dragonflow. Most of them are geared
towards verifying the pipeline was installed correctly.

::

    > sudo ovs-ofctl dump-flows br-int

This command will display the pipline that has been installed in OVS. See the
manual page for ovs-ofctl for more info.

It is worthwhile to note that each flow contains statistics such as how many
packets matched this flow, and what is the cummulative size.

::

    > sudo ovs-appctl ofproto/trace br-int <flow>


This command will simulate a packet matching the given flow through
the pipline.  The perl script in [#]_ can be used to facilitate the use
of this tool. The script also recirculates the packet when necessary,
e.g. for connection tracking.

..  [#] https://gist.github.com/omeranson/5c731955edcf0517bfb0ce0ce511cc9b
