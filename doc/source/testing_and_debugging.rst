=====================
Testing and Debugging
=====================

This page discusses the testing and debugging capabilities that come
with Dragonflow.

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

It is possible to have the fullstack tests take authentication information
from the environment variable, using e.g. an openrc file, such as provided
by devstack or openstack-ansible.

To do so, set the environment variable `DF_FULLSTACK_USE_ENV`

::

    > export DF_FULLSTACK_USE_ENV=1


Debugging
=========

There are a few tools that exist to debug Dragonflow. Most of them are geared
towards verifying the pipeline was installed correctly.

::

    > sudo ovs-ofctl dump-flows br-int -O OpenFlow13

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

::

   > df-db


This utility will allow to inspect Dragonflow northbound database. You can
dump db content, list db tables, list db table keys and print value of the
specific key in the table. Use *df-db --help* to list and get details on
supported sub-commands.

..  [#] https://gist.github.com/omeranson/5c731955edcf0517bfb0ce0ce511cc9b
