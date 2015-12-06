==============
Pluggable DB
==============

Instead of implementing a proprietary DB solution for Dragonflow or picking
one open source framework over the other, we designed the DB layer in
Dragonflow to be pluggable.

The DB framework is the mechanism to sync network policy and topology between the CMS and the
local controllers and hence control the performance, latency and scale of the environments
Dragonflow is deployed in.

This allows the operator/admin the flexibility of choosing and changing between DB
solutions to best fit his/her setup.
It also allows, with very minimal integration, a way to leverage the well tested and mature
feature set of these DB frameworks (clustering, HA, security, consistency, low latency and more..)

This also allows the operator/admin to pick the correct balance between performance and
latency requirements of their setup and the resource overhead of the DB framework.

Adding support for another DB framework is an easy process, all you need is to implement
the DB driver API class and add an installation script for the DB framework server and client.

The following diagram depicts the pluggable DB architecture in Dragonflow and the
currently supported DB frameworks:


Classes in the DB Layer
========================

Applicative N/B DB Adapter Layer
----------------------------------

DB Driver API
--------------


Modes of DB
============

Full Proactive
--------------

Selective Proactive
-------------------

Reactive
---------





