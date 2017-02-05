..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

=========================
North Bound Code Refactor
=========================

In this spec we will discuss the North Bound API, and how we want it to look.

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

The NB API will provide five methods:

* create
* update
* get
* get_all
* delete

Each method will receive a model instance. It will use the data in the model
to update the database (`id` for `get` and `delete`, other fields for `create`
and `update`).

A model will be able to extend these operations using metadata defined upon
model definition (see below).

For example, creating a logical port will look like so:

::

    self.nb_api.create(models.LogicalPort(id=..., name=..., ...))

Schematically, an implementation will do the following:

::

    def create(self, model_obj):
        model_obj.validate()
        val = jsonutils.dumps(model_obj.to_struct())
        write_to_db(model_obj.table_name, val)

Pros:
    * Every object can provide its own methods when needed
    * Table name constant on model can be used
    * Model registration can be automatic, and models can extend the basic CRUD
      functionality.
Cons:
    * Very long line to do a single operation, although the line can be broken
      up into parts.

This model can be used to promote dynamic registration: Upon import,
the model registers itself to a global store, providing any necessary metadata,
e.g. extensions on CRUD operations for NBApi and a CRUD Object for DBStore.

It is expected that the NB Api will be extended. Some models provide additional
functionality unique to that model, e.g. floating IPs would provide associate
and disassociate FIP methods.

These methods will be applied on the in-memory instance, and can only
be committed to the database using the basic CRUD methods. For instance:

::

    fip.assoc_port(lport)
    self.nb_api.update(fip)


Model Definition
----------------

We will use jsonmodels [1]_ to define models. The model definition will
look like this:

::

    @register_model
    @construct_nb_db_model(
        indexes=Namespace(id='id'),
        events=('create', 'update', 'delete'),
    )
    class <Model>(<ModelBaseClass>, <ModelMixins>):
        # Fields
        <ModelField1> = jsonmodels.StringField()
        <ModelReferenceField1> = jsonmodels.RefField()

        <CRUD hooks>

        # Additional methods, if necessary, e.g. lports external fields

<ModelBaseClass> will be a base class all models inherit.

Models will be registered via the `register_model` method. This method can be
used as a decorator, or called directly with the model.

External modules or model classes will have to register themselves manually
in a configuration file.

<ModelMixins> can be used to add additional recurring features to the model.
For instance, a unique key.

<CRUD hooks> are optional method definitions that will be called upon CRUD
operations performed in NbApi, e.g.

 * `on_create_pre` - Called on the object before its being inserted for the
   first time into the database, for example allocating a unique key.

 * `on_update_pre` - Called on the object each time it is updated, can be used
   for example to generate a new version or trigger updates on other objects.

Since those hooks are methods on objects themselves, we can use super() to
chain all needed hooks in parents and mixins, according to Python's native MRO.

The `construct_nb_db_model` decorator constructs the model as a NB DB model.
The metadata passed to it provides additional necessary information such as
search indexes and events. If some metadata is not provided, the relevant
information is taken from the parent classes and mixins.

The model class itself will hold the list of fields available on the object.
The instance will have attributes holding the fields' data.

These attributes can be made properties (rather than just holding the data)
with information added to the Field object. *This feature will only be added
if we see it is necessary.*

References are special kinds of fields. They have the type `RefField` or
`NestedField`, depending whether the field is referenced by its ID, or held
inline within the object, respectively.

For example, a logical port references a network by its ID, so the definition
will be:

::

    network = models.RefField(model='Network')

In another example, networks reference their subnets and contain the subnet
object. Therefore, the subnet definition within the network will be:

::

    subnet = models.NestedField(model='Subnet')

In this example, we assume exactly one subnet per network.

In both cases, when referencing the field, it will look as though the field
is nested within the parent model. If only the id field is accessed in a
`RefField` reference, then the ID will be returned. If a different field is
accessed, the model object will be retrieved.

This behaviour can be controlled, and the complete model object can be
retrieved a-priori.

The contained object may be a cached object, and that cache may be invalidated.
In such a case, the cache will mark the object as cache-invalid, and the object
will be re-read the next time it is accessed. This marking is possible, since
the object's reference is stored.

If nested resources are plural, e.g. a list, then the field will be defined
as a `ListField`. e.g. for subnets in networks:

::
    subnets = models.ListField(models.NestedField(...))

The metadata parameter `indexes` will provided the indexes that should
be constructed around the model. This is to facilitate lookup by field
value or filtering. An indexed field will allow looking up models that
have a specific value in that field.

As noted below, indexing nested object will also be supported. The
reference is done using dotted-notation, e.g. `router.ports.mac`.

Additionally, indexing by more than one field will also be supported, using
a tuple of fields. e.g. indexing an lport by both chassis name and network id
will look like this: `chassis_net=('chassis.name', 'network.id')`.

To support dynamic definition of events, i.e. to allow each model to
define its events, there will be an `events` metadata parameter. It will
be defined in greater detail upon southbound refactor.

The class can be extended with additional or overriding methods, if necessary.

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
instances by these fields (even if they are nested), and upon request use these
fields to extract the relevant instance.

Guiding Example
~~~~~~~~~~~~~~~

Suppose we want to support getting all routers by:

1. Tenant

2. MAC

The following metadata parameter will be passed:
`indexes=Namespace(topic='topic', macs='ports.mac')` The DB Store
implementation will index the `topic` and nested `mac` fields
automatically.

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

* Configuration file options (Can be done in parallel)

References
==========

.. [1] https://github.com/beregond/jsonmodels
