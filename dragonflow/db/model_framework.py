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

from jsonmodels import fields
from jsonmodels import models
from oslo_log import log
from oslo_serialization import jsonutils
import six

from dragonflow._i18n import _LE
import dragonflow.db.models as df_models

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
    def __init__(self, **kwargs):
        super(_CommonBase, self).__init__(**kwargs)
        self._set_fields = self._field_names.intersection(set(kwargs.keys()))

    @classmethod
    def from_json(cls, data):
        return cls(**jsonutils.loads(data))

    def to_json(self):
        return jsonutils.dumps(self.to_struct())

    def update(self, other):
        changed_fields = set()

        for key, _ in other.iterate_over_set_fields():
            old_value = getattr(self, key)
            new_value = getattr(other, key)

            if old_value != new_value:
                changed_fields.add(key)
                setattr(self, key, new_value)

        return changed_fields

    @classmethod
    def _emit(cls, event, *args, **kwargs):
        for cb in cls._event_callbacks[event]:
            try:
                cb(*args, **kwargs)
            except Exception:
                LOG.exception(
                    _LE('Error while calling %(func)r(*%(args)r, **%(kw)r)'),
                    extra={'func': cb, 'args': args, 'kw': kwargs},
                )

    @classmethod
    def _register(cls, event, cb):
        cls._event_callbacks[event].add(cb)

    @classmethod
    def _unregister(cls, event, cb):
        cls._event_callbacks[event].remove(cb)

    @classmethod
    def get_events(self):
        return set()

    @classmethod
    def get_indexes(self):
        return {}

    def on_create_pre(self):
        pass

    def on_update_pre(self):
        pass

    def on_delete_pre(self):
        pass

    @classmethod
    def on_get_all_post(cls, instances):
        return instances

    def __setattr__(self, key, value):
        super(_CommonBase, self).__setattr__(key, value)
        if key in self._field_names:
            if value is not None:
                self._set_fields.add(key)
            else:
                self._set_fields.discard(key)

    def iterate_over_set_fields(self):
        for name, field in self:
            if name in self._set_fields:
                yield name, field

    def field_is_set(self, name):
        return name in self._set_fields


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

    indexes = {k: _normalize_tuple(v) for k, v in six.iteritems(indexes)}

    def decorator(cls_):
        event_callbacks = collections.defaultdict(set)

        @classmethod
        def get_indexes(cls):
            res = super(cls_, cls).get_indexes()
            res.update(indexes)
            return res

        @classmethod
        def get_events(cls):
            return events.union(super(cls_, cls).get_events())

        cls_.get_indexes = get_indexes
        cls_.get_events = get_events

        for event in cls_.get_events():
            @classmethod
            def register_event(cls, cb):
                cls._register(event, cb)

            register_event_name = 'register_{0}'.format(event)
            register_event.__func__.__name__ = register_event_name
            setattr(cls_, register_event_name, register_event)

            @classmethod
            def unregister_event(cls, cb):
                cls._unregister(event, cb)

            unregister_event_name = 'unregister_{0}'.format(event)
            unregister_event.__func__.__name__ = unregister_event_name
            setattr(cls_, unregister_event_name, unregister_event)

            def emit_event(self, *args, **kwargs):
                self._emit(event, self, *args, **kwargs)

            emit_event_name = 'emit_{0}'.format(event)
            emit_event.__name__ = emit_event_name
            setattr(cls_, emit_event_name, emit_event)

        # Add non-method attributes after we set names
        cls_._event_callbacks = event_callbacks

        fields = set(n for n, _ in cls_.iterate_over_fields())
        cls_._field_names = fields

        return cls_

    if cls_ is None:
        return decorator
    else:
        return decorator(cls_)

_lookup_by_class_name = {}
_lookup_by_table_name = {}


@construct_nb_db_model(indexes={'all': (), 'id': ('id',)})
class ModelBase(_CommonBase):
    id = fields.StringField(required=True)


class MixinBase(_CommonBase):
    pass


def register_model(cls):
    _lookup_by_class_name[cls.__name__] = cls
    try:
        _lookup_by_table_name[cls.table_name] = cls
    except AttributeError:
        pass
    finally:
        return cls


def get_model(arg):
    """
    A function to retrieve registered models:
    * By class name
    * By table name (old+new models)
    """

    if type(arg) == type:
        return arg

    for lookup in (
        _lookup_by_class_name,
        _lookup_by_table_name,
        df_models.table_class_mapping,
    ):
        try:
            return lookup[arg]
        except KeyError:
            pass

    raise KeyError(arg)


def iter_models():
    for model in six.itervalues(_lookup_by_class_name):
        yield model


def iter_tables():
    for model in iter_models():
        yield model.table_name
