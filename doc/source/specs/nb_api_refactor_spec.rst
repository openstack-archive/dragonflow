..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
North Bound Code Refactor
=========================

In this (informal) spec we will discuss the North Bound API, and how we want it to look.

More specifically, we will delve in depth on how we want the following elements
to look:

* NB API

* DB Store API

* DB Models

With foresight to the following items:

* Southbound API refactor

  * DF Controller refactor

  * Dynamic message passing to and between applications

  * Dynamic adding of events to applications (e.g. CRUD on lport, routers)

* Dynamic registration of new models (for new features)

* Native Dragonflow API (e.g. REST)

Problem Description
===================

Currently the northbound API (and southbound API) is written in a hard-coded
manner which makes adding new models difficult. It requires modifications of
many files, and the modification usually include modified code.

We would like to find a new mechanism, with the following requirements:

* Simple, readable code structure

  * Model specific code is in a model-specific location

  * General code is in a general location (e.g. NbAPI)

* No hard-coding or tight coupling

* Support to easily add new models

* Within that, support for dynamic model registration (which may be done in future, or as an implementation of this spec)

* Simplify support for new external APIs

* Support search and indexing operations in DB store (e.g. ports by chassis, local ports, remote ports)

* Support special NB API operations (e.g. adding/removing router interfaces, adding/removing secgroup rules)

* Simple, localised changes when adding new models (e.g. for TAPaaS, FWaaS, SFC)

* Similar API for NBApi and DBStore (mostly for simplicity, readibility)

* *Please add anything I missed.*

Proposed Change
===============

There are several options being considered here:

Option 1
--------

Have objects as attributes on nbapi and dbstore. Calling a method is as follows:

::

    self.nb_api.lport.create(...)

Pros:
    * Simple, elegant, solution for existing models
    * Every object can provide its own methods when needed
Cons:
    * Manual registration for every model
    * Namespace pollution
    * Need to know attribute name of model (Can't use model's tablename const)

Option 2
--------

Pass model name to every method on nb_api. Calling a method is as follows:

::

    self.nb_api.create('lport', ...)

Pros:
    * Table name constant on model can be used
    * Model registration implementation is done 'Under the hood'. We can choose any implementation we like.
Cons:
    * Every method type has to be placed on nb_api/db_store. Therefore, add_lrouter_port will exist on nb_api, but will only be relevant for lrouters.

Option 3
--------

(My favorite)

A combination of both. Each model has a 'CRUD object', but is retrieved
dynamically.

::

    self.nb_api.get_resource('lport').create(...)


Pros:
    * Every object can provide its own methods when needed
    * Table name constant on model can be used
    * Model registration can be automatic, and models can provide their own 'CRUD helper'
    * synactic sugars such as nb_api.create can be used for well-known operations (e.g. create, get, update, delete)
Cons:
    * Very long line to do a single operation

This model can be used to promote dynamic registration: Upon import,
the model registres itself to a global store, providing a CRUD Object
for NBApi and a CRUDObject for DBStore.  These CRUD objects can include
additional functionality where needed. Basic functions are then provided
by the NBApi/DBStore, for the actual read/write to the NBDB and cache.

Need to think on how to add support for cache searching and indexing.

References
==========
None
