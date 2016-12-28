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
import functools

from jsonmodels import models
from oslo_serialization import jsonutils

from dragonflow.utils import namespace


def _combine_indexes(base_class, new_indexes):
    result = namespace.Namespace()

    if new_indexes is not None:
        result.impose_over(new_indexes)

    try:
        result.impose_over(super(base_class, base_class).get_indexes())
    except AttributeError:
        pass

    return result


class _CommonBase(models.Base):
    @classmethod
    def from_json(cls, data):
        return cls(**jsonutils.loads(data))

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def _emit(cls, event, *args, **kwargs):
        for cb in cls._get_event_callbacks()[event]:
            try:
                cb(*args, **kwargs)
            except Exception:
                pass

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

    def on_create(self):
        pass

    def on_update(self):
        pass

    @classmethod
    def get_all(cls, instances):
        return instances


class ModelBase(_CommonBase):
    pass


class MixinBase(_CommonBase):
    pass


def construct_nb_db_model(cls_=None, indexes=None, events=()):
    if indexes is None:
        indexes = namespace.Namespace()

    def decorator(cls_):
        callback_lookup = collections.defaultdict(set)

        class ConstructedClass(cls_):
            @classmethod
            def get_indexes(cls):
                result = indexes.copy()
                result.impose_over(super(ConstructedClass, cls).get_indexes())
                return result

            @classmethod
            def get_events(cls):
                base_events = super(ConstructedClass, cls).get_events()

                # FIXME this is done too many times, need to discard only once
                return tuple(set(events + base_events))

            @classmethod
            def _get_event_callbacks(cls):
                cls.lookup = callback_lookup
                return callback_lookup

        extra_attributes = {}
        for event in ConstructedClass.get_events():
            extra_attributes['register_{0}'.format(event)] = functools.partial(
                ConstructedClass._register, event)

            extra_attributes['unregister_{0}'.format(event)] = (
                functools.partial(ConstructedClass._unregister, event))

            extra_attributes['emit_{0}'.format(event)] = functools.partial(
                ConstructedClass._emit, event)

        return type(cls_.__name__, (ConstructedClass,), extra_attributes)

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
    if type(arg) == type:
        return arg
    try:
        return _lookup_by_class_name[arg]
    except KeyError:
        pass
    return _lookup_by_table_name[arg]
