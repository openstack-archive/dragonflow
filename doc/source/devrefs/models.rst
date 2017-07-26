..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

      Convention for heading levels:
      =======  Heading 0 (reserved for the title in a document)
      -------  Heading 1
      ~~~~~~~  Heading 2
      +++++++  Heading 3
      '''''''  Heading 4
      (Avoid deeper levels because they do not render well.)

Models
======

Dragonflow, as many other projects interfacing with a database, uses model
layer to allow uniform and easy access to data stored in the (north-bound)
database. The current model framework is a fruit of the :doc:`../specs/nb_api_refactor`

Creating new models
-------------------

Each new model should be defined as a subclass of `ModelBase`, and decorated
with `construct_nb_db_model` decorator. Below we'll introduce an example:

.. code-block:: python

   @model_framework.construct_nb_db_model
   class Movie(model_framework.ModelBase):
       table_name = 'movies'

       title = fields.StringField(required=True)
       year = fields.IntField()
       director = fields.ReferenceField(Director)
       awards = fields.ListField(str)

The above example defines a new `Movie` model, that contains 5 fields:

 #. `id` - Object identifier, derived form ModelBase, present in all model objects.
 #. `title` - A string containing the movie title, marked as mandatory.
 #. `year` - A year movie was published.
 #. `director` - A reference field to an object of director type (will be covered later).
 #. `awards` - A list of all the awards the movie received.

Class definition also contains `table_name` field that stores the name of the table
our model is stored in the north-bound database.


Initializing this object is done by passing the values as keyword arguments.

.. code-block:: python

   a_space_oddyssey = Movie(
       id='movie-id-2001',
       title='2001: A Space Oddyssey',
       year=1968,
       director=Director(id='stanley-kubrick')
       awards=[
           'Academy Award for Best Visual Effects',
       ],
   )


We expect to write our data to the database as JSON document, the above object
will be translated to:

.. code-block:: json

   {
       "id": "movie-id-2001",
       "title": "2001: A Space Oddyssey",
       "year": 1968,
       "director": "stanley-kubrick",
       "awards": ["Academy Award for Best Visual Effects"]
   }


Registry
--------

The model framework provides another decorator, @register_model that adds the
class to an internal lookup table.

This allows iterating of registered models, and retrieving models by class
name or table name, e.g:

.. code-block:: python

   for model in iterate_models():
       instances = db_store.get_all(model)

or

.. code-block:: python

   movie_class = get_model('movies')
   movie = movie_class(**params)

References
----------

Oftentimes one model is related to another object in some manner, consider the
movie example above, each movie has a director, so somewhere in our code we
have a director model, in the form of:

.. code-block:: python

   class Director(ModelBase):
       table_name = 'directors'

       full_name = fields.StringField()

In order to allow easy association and lookup, we can define a reference field
that will retrieve the actual object (by its ID) behind the scenes. Consider
we have the following object in our database:

.. code-block:: python

   kubrick = Director(id='stanley-kubrick', full_name='Stanley Kubrick')

We how can access `kubrick` object through `a_space_oddyssey.director`, e.g.

.. code-block:: python

   >>> a_space_oddyssey.director.full_name
   Stanley Kubrick


The fetching is done behind the scenes (first from the local cache, then from
the northbound database).


Events
------

Each model can define an arbitrary set of events, which can be used to invoke
callbacks on various conditions, events are inherited from parent classes, and
are specified in `events=` parameter of construct_nb_db_model decorator:

.. code-block:: python


   @construct_nb_db_model(events={'premiered'})
   class Director(ModelBase):
       # ...

For each event, 2 class methods are defined:

 * `register_{event_name}(callback)` - adds callback to be invoked each time
   event is emitted.
 * `unregister_{event_name}(callback)` - removes the callback from being called.

Additionally, an instance method named `emit_{event_name}(*args, **kwargs)` is
added.

Emit can only be called on an instance, and the origin instance is passed as
first parameter to all the callbacks, then, `*args`, and `**kwargs` follow. So
a call

.. code-block:: python

   a_space_oddyssey.emit_premiered(1, 2, 3, a='a', b='b')

would be translated to a sequence of

.. code-block:: python

   callback(a_space_oddyssey, 1, 2, 3, a='a', b='b')

The convention of parameters is specific to each event.

The register calls can be also used as decorators for some extra syntactic sugar

.. code-block:: python

   @Movie.register_premiered
   def on_premiere(movie):
       print('{title} has pemiered'.format(title=movie.title))

Indexes
-------

To allow easy retrieval and lookup of in memory objects we use DbStore module
to fetch by IDs and other properties, the new DbStore takes note of model's
indexes and creates lookups to allow faster retrieval. Indexes, similar to events
are passed in `indexes=` parameter of construct_nb_db_model decorator and
specified as a dictionary where the key is the index name and the value is the
field indexed by (or a tuple of fields, if the index is multi-key). For example
if we'd like to add index by year we can define it as:

.. code-block:: python

   @construct_nb_db_model(indexes={'by_year': 'year'})
   class Director(ModelBase):
       # ...

then query db_store by providing the index and the keys:

.. code-block:: python

   all_1968_movies = db_store.get_all(
       Movie(year=1968),
       index=Movie.get_index('by_year'),
   )

Hooks
-----
We can also define several entry points to be called on various CRUD event in
the north-bound API, for example, if we wished to track our access movie and
director objects better we could define a common class:

.. code-block:: python

   class AccessMixin(MixinBase):
       created_at = fields.DateTimeField()
       updated_at = fields.DateTimeField()

       def on_create_pre(self):
           super(AccessMixin, self).on_create_pre()
           self.created_at = datetime.datetime.now()

       def on_update_pre(self):
           super(AccessMixin, self).on_update_pre()
           self.updated_at = datetime.datetime.now()

The above code updates the relevant fields on create/update operations, so if
we add those as parent class in our Movie or Director classes we'll receive
the new functionality:

.. code-block:: python

   # ...
   class Movie(ModeBase, AccessMixin):
       # ...
