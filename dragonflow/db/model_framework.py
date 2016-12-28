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

from jsonmodels import models
from oslo_log import log
from oslo_serialization import jsonutils
import six

from dragonflow._i18n import _LE
import dragonflow.db.models as df_models
from dragonflow.utils import namespace

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
    @classmethod
    def from_json(cls, data):
        return cls(**jsonutils.loads(data))

    def to_json(self):
        return jsonutils.dumps(self.to_struct())

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def _emit(cls, event, *args, **kwargs):
        for cb in cls._get_event_callbacks()[event]:
            try:
                cb(*args, **kwargs)
            except Exception:
                LOG.exception(
                    _LE('Error while calling %(func)r(*%(args)r, **%(kw)r)'),
                    extra={'func': cb, 'args': args, 'kw': kwargs},
                )

    @classmethod
    def _register(cls, event, cb):
        cls._get_event_callbacks()[event].add(cb)

    @classmethod
    def _unregister(cls, event, cb):
        cls._get_event_callbacks()[event].remove(cb)

    @classmethod
    def get_events(self):
        return ()

    @classmethod
    def get_indexes(self):
        return namespace.Namespace()

    def on_create_pre(self):
        pass

    def on_update_pre(self):
        pass

    def on_delete_pre(self):
        pass

    @classmethod
    def on_get_all_post(cls, instances):
        return instances


class ModelBase(_CommonBase):
    pass


class MixinBase(_CommonBase):
    pass


def construct_nb_db_model(cls_=None, indexes=None, events=()):
    """This decorator acts upon model class definition and adds several methods
    that include:
        * The events and indexes defined for the object
        * Registration and de-registration for events
        * Emitting events.

    This is done by deriving from the provided class and extending the new type
    with the aforementioned methods.
    """
    if indexes is None:
        indexes = namespace.Namespace()
    else:
        indexes = namespace.Namespace(**{
            k: _normalize_tuple(v) for k, v in indexes
        })

    def decorator(cls_):
        callback_lookup = collections.defaultdict(set)

        @classmethod
        def get_indexes(cls):
            result = indexes.copy()
            result.impose_over(super(cls_, cls).get_indexes())
            return result

        @classmethod
        def get_events(cls):
            base_events = super(cls_, cls).get_events()

            return tuple(set(events + base_events))

        @classmethod
        def _get_event_callbacks(cls):
            return callback_lookup

        extra_attributes = {}
        extra_attributes['get_indexes'] = get_indexes
        extra_attributes['get_events'] = get_events
        extra_attributes['_get_event_callbacks'] = _get_event_callbacks
        for event in tuple(set(events + cls_.get_events())):
            @classmethod
            def register_event(cls, cb):
                cls._register(event, cb)

            @classmethod
            def unregister_event(cls, cb):
                cls._unregister(event, cb)

            def emit_event(self, *args, **kwargs):
                self._emit(event, self, *args, **kwargs)

            extra_attributes['register_{0}'.format(event)] = register_event
            extra_attributes['unregister_{0}'.format(event)] = unregister_event
            extra_attributes['emit_{0}'.format(event)] = emit_event

        # Fix method names:
        # We defined event methods above with generic names because we cannot
        # use a string there. To fix this we iterate all of them and set their
        # name as it appears in the class dict
        for name, attr in six.iteritems(extra_attributes):
            try:
                attr.__func__.__name__ = name
            except AttributeError:
                attr.__name__ = name

        return type(cls_.__name__, (cls_,), extra_attributes)

    if cls_ is None:
        return decorator
    else:
        return decorator(cls_)

_lookup_by_class_name = {}
_lookup_by_table_name = {}


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
