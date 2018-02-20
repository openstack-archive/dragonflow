..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 https://creativecommons.org/licenses/by/3.0/legalcode

===================
SkyDive integration
===================

Relevant launchpad RFE:

https://bugs.launchpad.net/dragonflow/+bug/1749429

Currently we do not have an easy way to visualize the way Dragonflow sees the
topology and the relations between topology elements. This view is important
both for operators using Dragonflow, and for developers trying to debug the
system.

To solve this, we would like to leverage one of the SkyDive [1]_ project
capabilities - being a good topology visualization tool. This will allow
us to provide the overall topology view (skydive model) and use the skydive
for all the different ways to visualize and dissect the information (skydive
view).


Problem Description
===================

Add the ability to view the topology as known by DragonFlow in a graphical way.
This feature is needed to allow easier debugging of issues in flows and
understanding the behaviour of DragonFlow.

Implementation stages:

1. Have a view of the topology of a specific chassis (Node running
   Dragonflow controller)
2. Have real-time updates of the information (topology elements added/removed)
3. Allow aggregation of the information and have a global view of the
   topology, which means the view of the entire network as Dragonflow sees it
4. Allow filtering and dissecting of the information to show just specific
   parts
5. Allow simulation or tracing of packets in the system on the graphical
   interface

All of these features are supported by skydive project, but for other
agent types.
What we need to do is implement our own agent (or a way to send the
information to the analyser) in a way that will be out-of-band with the
operation of the controller (or at least not block it for long periods).
Another thing we should provide is to allow an administrator (rather than
developer) easy access and debugging of the system.

Proposed Change
===============

Add one Skydive analyzer with one (or more) skydive agents.
The agents are responsible to collect the topology information,
translate it to the Skydive model structure and send it to the analyzer.
The Analyzer, in turn, is responsible to aggregate the information and for
the displaying of the information, with/without filtering requested by the
end-user (be it a developer / integrator / operator).

The agents will run on the Dragonflow Controller nodes as a separate
service (not within the controller) for several reasons:

1. We do not want to affect the performance of the controller. Each update
   sent to the analyzer may take up to a few seconds, in which time the
   controller will not be able to service other requests
2. The code running in the controller must be monkey_patched (as it is using
   the oslo infrastructure and the etcd driver with both require
   monkey_patching). This creates different limitations on our code - e.g.
   the asyncio loops and selectors are limited or behave badly

Integration should be done in several stages:

1. Create a basic service that runs every given period and sends an update
   of the elements in the system to the analyzer.
2. Support topology update, including removal of objects from the DB and
   reflect it in the topology view in SkyDive.
3. Handle cases of disconnect/re-authentication between the collector and the
   analyzer
4. Handle cases of disconnect/reconnect of the collector and the nb_db
5. Add a mechanism in which the skydive_service will get notification of
   objects that were added-to/removed-from the topology to have an
   experience that is closer to real-time as opposed to periodic updates.
6. Specify an API for DragonFlow applications to add custom information to
   the topology view (e.g. port-behind-port) and relevant metadata to be
   used in the view filtering.
7. Improve the visualization (custom icons, etc.)
8. Add some SkyDive views / filters.
9. In the nb_db the router only points to the internal network ports, so the
   view we get is not complete. We would like it to point to the its gateway
   port as well. To achieve that we would have to add some kind of proxy
   object (as we have the table name and owner ID) to be able to retrieve this
   gateway port from the nb_db.

Open issues / feature discussion:
=================================

- How do we get the topology change notifications? As we are an external
  application we disable the pubsub feature, so we should have a different
  way of getting these notifications.
  One solution may be using the pubsub mechanism, but it will require
  rewriting (at least) the etcd pub/sub subscriber driver to use (e.g.)
  etcd3gw or etcd3 library (for patched code or not) so we can support
  both cases for different use-cases.

I believe that a separate spec would have to cover these:
- What views / filters do we want to supply - need to investigate how to
  define them.
- If possible, we would like to support the option to emulate a passing
  of a packet through the system. Is it supported by SkyDive? if so, how?
- If possible, we would like to support visualization of tracing of packets
  in our system. Is it supported by SkyDive? if so, how?
  What is required on our side to visualize it on SkyDive?

References
==========

.. [1] SkyDive project: http://skydive-project.github.io/skydive/
.. [2] SkyDive intro: https://www.youtube.com/watch?v=nQSdGKV8ceM