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

  * Application manager which chains and orders applications according to their
    dependencies.

* Allow new models to register their NB API and DB Store functionality.

* Native Dragonflow API (e.g. REST)

Problem Description
===================

Currently the northbound API (and southbound API) is written in a hard-coded
manner which makes adding new models difficult. It requires modifications of
many files, and the modification usually include duplicated code.

We would like to find a new mechanism, with the following requirements:

* Simple, readable code structure

  * Model specific code is in a model-specific location

  * General code is in a general location (e.g. NbAPI)

* No hard-coding or tight coupling

* Extendability, i.e. support to easily add new models

* Compartmentalisation of code, i.e. allowing different developers to split the
  work of a new feature between them

* Within that, support for dynamic model registration. i.e. allow models to be
  able to register themselves. A client developer would only define a model,
  register it (e.g. using a decorator or registration function), and it will
  exists in the NbApi and DbStore.

* Simplify support for new external APIs. In the future, we will want to add
  additional APIs to Dragonflow (e.g. Native API, Gluon). The change here
  should facilitate that.

* Support search and indexing operations in DB store (e.g. ports by
  chassis, local ports, remote ports)

* Support special NB API operations (e.g. adding/removing router
  interfaces, adding/removing secgroup rules)

* Simple, localised changes when adding new models (e.g. for TAPaaS,
  FWaaS, SFC)

* Similar API for NBApi and DBStore (mostly for simplicity, readibility)

* Uniform call to NbApi's and DBStore's get. e.g. to allow a call to DBStore's
  get to fall through to NbApi if the object doesn't exist in the DBStore.

* Dragonflow specific CLI. Including integration of relevant bits into
  openstack pythonclient.

* Dragonflow upgrade scenario, i.e. replacing an existing Dragonflow
  implementation with a newer version

* *Please add anything I missed.*

Proposed Change
===============

Each model has a 'CRUD object'. The CRUD object is retrieved dynamically.

::

    self.nb_api.get_resource('lport').create(...)


Pros:
    * Every object can provide its own methods when needed
    * Table name constant on model can be used
    * Model registration can be automatic, and models can provide their own 'CRUD helper'
    * syntactic sugars such as nb_api.create can be used for well-known operations (e.g. create, get, update, delete)
Cons:
    * Very long line to do a single operation

This model can be used to promote dynamic registration: Upon import,
the model registres itself to a global store, providing a CRUD Object
for NBApi and a CRUD Object for DBStore.

CRUD objects can include additional functionality where needed. Basic
functionality is then provided by the NBApi/DBStore, for the actual
read/write to the NBDB and cache.

These CRUD objects will have a base class all CRUD objects are expected to
extend. The Db Store CRUD object will be provided by Db Store code, and is
not expected to be extended by model developers.

Model Definition
----------------

The model definition (of a resource) will look like this:

::

    @register_model
    class <Model>(<ModelBaseClass>, <ModelMixins>):
        # If different from what's provided by the mixins
        crud_nb_api = <CRUD Helper>
        fields = ['<ModelField1>', '<ModelReferenceField1>', ...]
        nested = ['<NestedModel1>', ...]
        indexes = ['<IndexedField1>', ...]
        # Events definition will go here
        ... # Additional methods, if necessary, e.g. lports external fields

<ModelBaseClass> will be a base class all mdoels inherit.

Models will be registered via the `register_model` method. This method can be
used as a decorator, or called directly with the model.

External modules or model classes will have to register themselves manually
in a configuration file.

<ModelMixins> can be used to add additional recurring features to the model.
For instance, a unique key.

The class field `crud_nb_api` will hold a getter for a CRUD helper object.
The CRUD helper object will contain create, get, update, and delete methods, as
well as any other methods provided by the model (e.g. associate and
disassociate floating IPs).

The getter received an instance of the NB API, so that it will be able to
interact with the database driver. It may be any callable accepting exactly
one parameter.

Nb Api's new `get_resource` method will call <Model>'s `crud_nb_api` with
itself as the only parameter.

<ModelBaseClass> will hold a basic CRUD helper, providing the four basic CRUD
methods: `create`, `get`, `update`, and `delete`. A <ModelMixin> may override
this field to provide a CRUD helper with additional methods.

The class field `fields` will hold a list of fields available on the object.
getter functions can be generated automatically, in the form of
`get_<fieldname>` for every field in `fields`, unless such a method already
exists. The representation of the field is transparent to the model definition,
provided it can natively be serialised using e.g. jsonutils or msgpack.

The class field `nested` will hold a dictionary of field name to model class.
The meaning here is that the field value will be an instance of that model.
This allows resources to contain other resources, e.g. routers and their ports,
or security groups and their rules. This will also allow splitting nested
resources into separate NB tables, if desired.

Nested resources are 'owned' by their parents. Therefore, this relationship is
only suitable for a 1-to-1 or 1-to-many relation.  many-to-many relations
cannot be used here.

The class field `indexes` will provided the indexes that should be constructed
around the model. This is to facilitate lookup by field value or filtering. An
indexed field will allow looking up models that have a specific value in that
field.

To support dynamic definition of events, i.e. to allow each model to define its
events, there will be an `events` class field. It will be defined in greater
detail upon southbound refactor.

The class can be extended with additional or overriding methods, if necessary.

Optionally, Nb Api will have four methods: `create`, `get`, `update`,
and `delete`, receiving a table name, and the parameters to the relevant
method. These will be facility methods calling the relevant function on
the resource's `crud_nb_api`. An example implementation will be:

::

    def create(self, table_name, **columns):
        resource = self.get_resource(table_name)
        crud_nb_api = resource.crud_nb_api(self)
        return crud_nb_api.create(columns)

An automatic migration script can review the difference between models, and
create the relevant migration code. This should also facilitate upgrading
Dragonflow to newer versions. Reverting back will not be supported.

Searching and Indexing
----------------------

As part of the requirements, a model developer should have a way to inform the
DB Store (in-memory cache) of which indexing and retrieval methods the model
needs to support. e.g.

* get all resources filtered by a field:

  * ports by chassis

  * ports by name

  * floating IP by gateway

* get all resources filtered by a nested field:

  * router by router interface mac, i.e. router by router interface, router
    interface by mac.

* get first item, possibly filtered by topic or other fields:

  * get first floating ip in a network

For these requirements, it is enough to define on a model the fields by which
it will be filtered. The internal DB store implementation will index the cached
instances by these fields (even if they are nested), and upon request use thse
fields to extract the relevant instance.

Guiding Example
~~~~~~~~~~~~~~~

Suppose we want to support getting all routers by:

1. Tenant

2. MAC

The `crud_cache` class field will need the following indexing information:
`topic`, and `ports.mac`. The `crud_cache` implementation will index the
`topic` and nested `mac` fields automatically.

Proposed Implementation
~~~~~~~~~~~~~~~~~~~~~~~

The DB Store will have, for each model, a map from instance's `id` to
its object. For each direct indexing field (e.g. `topic` in the example
above), the DB Store will hold a map from the indexed field to a list
of objects with that field's value. Since the objects are stored by
reference, there will be no object duplication between the maps.

For nested field indexing (e.g. `ports.mac` above), there will be a map between
the field to all the objects with that nested field value. If the intermediate
fields hold lists or sets, then each such collection will be iterated. In case
dictionaries, the values will be iterated.

The implementation detail of the indexing DB Store will be hidden from the
client developer, to allow us to replace it with a better implementation, if
and when possible. Therefore, additional API tests will be written to verify
the behaviour stays the same accross implementations.

An in-memory sqlite implementation was considered. However, sqlite stores
information as strings rather than python objects. Whilst serialisation and
de-serialisation is possible, it remains to be seen if it improves performance.
Since the DB Store implementation is hidden from client developers, a future
phase can implement Db Store in several different ways, and compare their
relative performance (e.g. using Rally).

Work Items
==========

* Registration Decorator and Function
  https://review.openstack.org/#/c/410645/

* Base CRUD Helper object

* New Db Store implementation

* Write method that constructs model classes and DbStore info, including
  migration code where necessary

* Move models to new structure (Can be done in parallel after the item above)

* Add new API to NbApi

* Move caller code to use new API

* Remove legacy API

* Automatic migration code (Can be done in parallel)

* Configuration file options (Can be done in parallel)

References
==========

None
