#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import collections
import copy
import functools

from jsonmodels import fields
from jsonmodels import models
from oslo_log import log
from oslo_serialization import jsonutils
import six

from dragonflow._i18n import _

LOG = log.getLogger(__name__)


def _normalize_tuple(v):
    """Convert strings to tuples of length one, other iterables to tuples

       >>> _normalize_tuple('hello')
       ('hello',)

       >>> _normalize_tuple(['a', 'b'])
       ('a', 'b')
    """
    if isinstance(v, six.string_types):
        return v,

    return tuple(v)


class _CommonBase(models.Base):
    '''Base class for extending jsonmodels' Base

    Here we add common facilites needed to support:

     * Event registration/dispatch
     * CRUD hooks
     * Serialization
     * Indexes
     * Unset field detection
    '''
    def __init__(self, **kwargs):
        for key in kwargs:
            if key not in self._field_names:
                raise TypeError(
                    _('{field} is not a field of {model}').format(
                        field=key,
                        model=type(self).__name__,
                    )
                )
        super(_CommonBase, self).__init__(**kwargs)
        self._set_fields = set(kwargs.keys()).intersection(self._field_names)
        self._is_object_stale = False

    @classmethod
    def from_json(cls, data):
        '''Instantiate current class from JSON encoded string'''
        return cls(**jsonutils.loads(data))

    def to_json(self):
        '''Convert object to JSON formatted string'''
        return jsonutils.dumps(self.to_struct())

    def update(self, other):
        '''Update the set fields from other instance, taking only the fields
        that were explicitly set (e.g. setting a field to None will copy it
        while omitting it will do nothing). If a new value of a field is the
        same as the old value, it is not considered changed.

        Returns a set of all changed fields.
        '''

        changed_fields = set()

        for key, value in other.iterate_over_set_fields():
            old_value = getattr(self, key)
            new_value = getattr(other, key)

            if old_value != new_value:
                changed_fields.add(key)
                if new_value is not None:
                    setattr(self, key, new_value)
                else:
                    delattr(self, key)

        return changed_fields

    def _emit(self, event, *args, **kwargs):
        for cb in self._event_callbacks[event]:
            LOG.debug("%(func)s from %(module)s gets %(event)s event of "
                      "%(resource)r.",
                      {'func': cb.__name__,
                       'module': cb.__module__,
                       'event': event,
                       'resource': self})
            try:
                cb(self, *args, **kwargs)
            except Exception:
                LOG.exception(
                    'Error while calling %(func)r(*%(_args)r, **%(kw)r)',
                    extra={'func': cb, '_args': args, 'kw': kwargs},
                )

    @classmethod
    def register(cls, event, cb):
        '''Registers `cb` to be called each time `event` is emitted'''
        cls._event_callbacks[event].add(cb)
        return cb

    @classmethod
    def unregister(cls, event, cb):
        '''Unregisters `cb` from being called each time `event` is emitted'''
        cls._event_callbacks[event].remove(cb)

    @classmethod
    def clear_registered_callbacks(cls):
        cls._event_callbacks.clear()

    @classmethod
    def get_events(cls):
        '''Events defined for this model'''
        return frozenset()

    @classmethod
    def get_indexes(cls):
        '''Indexes defined for this model'''
        return {}

    def on_create_pre(self):
        '''Hook function called before object is inserted for the first time
        into the NB database.
        '''
        pass

    def on_update_pre(self):
        '''Hook function called before object is updated in the NB database.
        '''
        pass

    def on_delete_pre(self):
        '''Hook function called before object is removed from the NB database.
        '''
        pass

    @classmethod
    def on_get_all_post(cls, instances):
        '''Hook function to filter and augment the results get_all from NB
        database.
        '''
        return instances

    def __setattr__(self, key, value):
        super(_CommonBase, self).__setattr__(key, value)
        if key in self._field_names:
            self._set_fields.add(key)

    def __delattr__(self, key):
        if key in self._field_names:
            setattr(self, key, None)
            self._set_fields.discard(key)
        else:
            super(_CommonBase, self).__delattr__(key)

    def iterate_over_set_fields(self):
        for name, field in self:
            if name in self._set_fields:
                yield name, field

    def field_is_set(self, name):
        '''Checks whether a fields was set on current object'''
        return name in self._set_fields

    def __copy__(self):
        fields = {name: getattr(self, name)
                  for name, _field in self.iterate_over_set_fields()}
        return self.__class__(**fields)

    def __deepcopy__(self, memo):
        fields = {name: copy.deepcopy(getattr(self, name), memo)
                  for name, _field in self.iterate_over_set_fields()}
        return self.__class__(**fields)

    def __repr__(self):
        fields = ["{}={}".format(name, repr(getattr(self, name)))
                  for name, _field in self.iterate_over_set_fields()]
        return "{}({})".format(self.__class__.__name__, ", ".join(fields))

    @classmethod
    def dependencies(cls):
        deps = set()
        for key, field in cls.iterate_over_fields():
            if isinstance(field, fields.ListField):
                types = field.items_types
            else:
                types = field.types

            for field_type in types:
                try:
                    deps.add(field_type.get_proxied_model())
                except AttributeError:
                    if issubclass(field_type, ModelBase):
                        # If the field is not a reference, and it is a df
                        # model(derived from ModelBase), it is considered as
                        # non-first class model. And its dependency
                        # will be treated as current model's dependency.
                        deps |= field_type.dependencies()

        return deps

    @classmethod
    def is_first_class(cls):
        return hasattr(cls, 'table_name')

    @classmethod
    def iterate_embedded_model_types(cls):
        embedded_models = set()

        for name, field in cls.iterate_over_fields():
            if isinstance(field, fields.EmbeddedField):
                models = field.types
            elif isinstance(field, fields.ListField):
                models = field.items_types
            else:
                continue

            for model in models:
                if issubclass(model, ModelBase):
                    if model not in embedded_models:
                        embedded_models.add(model)
                        yield model

                    for submodel in model.iterate_embedded_model_types():
                        if submodel not in embedded_models:
                            embedded_models.add(submodel)
                            yield submodel

    def iterate_embedded_model_instances(self):
        for name, field in self.iterate_over_set_fields():
            if isinstance(field, fields.EmbeddedField):
                subobjs = (getattr(self, name),)
            elif isinstance(field, fields.ListField):
                subobjs = getattr(self, name)
            else:
                continue

            for subobj in subobjs:
                if isinstance(subobj, ModelBase):
                    yield subobj

    @classmethod
    def get_index(cls, index):
        return cls.get_indexes()[index]


def _setattr_no_overwrite(obj, attr_name, attr):
    if hasattr(obj, attr_name):
        return
    setattr(obj, attr_name, attr)


def _add_event_funcs(cls_, event):
    @classmethod
    def register_event(cls, cb):
        return cls.register(event, cb)

    register_event_name = 'register_{0}'.format(event)
    register_event.__func__.__name__ = register_event_name
    _setattr_no_overwrite(cls_, register_event_name, register_event)

    @classmethod
    def unregister_event(cls, cb):
        cls.unregister(event, cb)

    unregister_event_name = 'unregister_{0}'.format(event)
    unregister_event.__func__.__name__ = unregister_event_name
    _setattr_no_overwrite(cls_, unregister_event_name, unregister_event)

    def emit_event(self, *args, **kwargs):
        return self._emit(event, *args, **kwargs)

    emit_event_name = 'emit_{0}'.format(event)
    emit_event.__name__ = emit_event_name
    _setattr_no_overwrite(cls_, emit_event_name, emit_event)


def construct_nb_db_model(cls_=None, indexes=None, events=frozenset()):
    """This decorator acts upon model class definition and adds several methods
    that include:
        * The events and indexes defined for the object
        * Registration and de-registration for events
        * Emitting events.

    This is done by deriving from the provided class and extending the new type
    with the aforementioned methods.
    """
    if indexes is None:
        indexes = {}

    indexes = {k: _normalize_tuple(v) for k, v in indexes.items()}

    def decorator(cls_):
        event_callbacks = collections.defaultdict(set)

        @classmethod
        @functools.wraps(_CommonBase.get_indexes)
        def get_indexes(cls):
            res = super(cls_, cls).get_indexes()
            res.update(indexes)
            return res

        @classmethod
        @functools.wraps(_CommonBase.get_events)
        def get_events(cls):
            return super(cls_, cls).get_events().union(events)

        cls_.get_indexes = get_indexes
        cls_.get_events = get_events

        for event in cls_.get_events():
            # Do this in a function to escape lexical scope issues
            _add_event_funcs(cls_, event)

        # Add non-method attributes after we set names
        cls_._event_callbacks = event_callbacks

        fields = frozenset(n for n, _ in cls_.iterate_over_fields())
        cls_._field_names = fields

        return cls_

    if cls_ is None:
        return decorator
    else:
        return decorator(cls_)


_registered_models = set()
_lookup_by_class_name = {}
_lookup_by_table_name = {}


@construct_nb_db_model(indexes={'id': ('id',)})
class ModelBase(_CommonBase):
    id = fields.StringField(required=True)


class MixinBase(_CommonBase):
    pass


def register_model(cls):
    '''Registers model into the lookup so it can be found later by name or
    by table name.
    '''

    if not cls.is_first_class():
        raise RuntimeError(
            _('Non first-class {0} model cannot be registered').format(
                cls.__name__,
            ),
        )

    if cls.__name__ in _lookup_by_class_name:
        raise RuntimeError(
            _('Cannot register class named {0}, '
              'another class with same name exists').format(cls.__name__),
        )

    if cls.table_name in _lookup_by_table_name:
        raise RuntimeError(
            _('Cannot register {0} to table {1}, '
              'already occupied by {2}').format(
                  cls.__name__,
                  cls.table_name,
                  _lookup_by_table_name[cls.table_name].__name__,
            ),
        )

    _registered_models.add(cls)
    _lookup_by_class_name[cls.__name__] = cls
    _lookup_by_table_name[cls.table_name] = cls

    for model in cls.iterate_embedded_model_types():
        _registered_models.add(model)
        _lookup_by_class_name[model.__name__] = model

    return cls


def get_model(arg):
    '''A function to retrieve registered models:
       * By class name
       * By table name (old+new models)
    '''

    if type(arg) == type:
        return arg

    for lookup in (
        _lookup_by_class_name,
        _lookup_by_table_name,
    ):
        try:
            return lookup[arg]
        except KeyError:
            pass

    raise KeyError(arg)


def iter_models(first_class_only=True):
    '''Iterate over all registered models'''
    for model in _registered_models:
        if first_class_only and not model.is_first_class():
            continue

        yield model


def iter_tables():
    '''Iterate over all table names any of the models define'''
    for key in _lookup_by_table_name:
        yield key


def iter_models_by_dependency_order(first_class_only=True):
    '''Iterate over all registered models

       The models are returned in an order s.t. a model never preceeds its
       dependencies.
    '''
    unsorted_models = {}
    # Gather all models and their dependencies
    for model in iter_models(first_class_only=first_class_only):
        dependencies = model.dependencies()
        if first_class_only:
            dependencies = {dep
                            for dep in dependencies if dep.is_first_class()}
        unsorted_models[model] = dependencies

    # Perform a topological sort
    sorted_models = []
    while unsorted_models:
        # Split models to those that still depend on something and those
        # that no more depend on models in unsorted_models
        dependent_models = set(k for k, v in unsorted_models.items() if v)
        independent_models = set(unsorted_models.keys()) - dependent_models

        # If we still have unsorted models yet nothing is independent, we have
        # dependency cycle
        if not independent_models:
            raise RuntimeError(_('Models form a dependency cycle'))

        # Move independent models to sorted list
        for model in independent_models:
            sorted_models.append(model)
            del unsorted_models[model]

        # Remove independent models from remaining dependency lists
        for model in dependent_models:
            unsorted_models[model] -= independent_models

    return sorted_models
