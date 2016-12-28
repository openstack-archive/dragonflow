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


def _combine_events(base_class, new_events):
    try:
        base_events = tuple(super(base_class, base_class).get_events())
    except AttributeError:
        base_events = ()

    if new_events is None:
        new_events = ()

    return tuple(set(new_events + base_events))


class ModelBase(models.Base):
    @classmethod
    def from_json(cls, data):
        return cls(**jsonutils.loads(data))

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def get_nb_crud(cls, *args, **kwargs):
        nb_crud_type = cls._get_nb_crud_type()
        if nb_crud_type is not None:
            return nb_crud_type(cls, *args, **kwargs)


def construct_nb_db_model(cls_=None, indexes=None, events=None, nb_crud=None):
    def decorator(cls_):
        # Compute results ahead of time
        result_indexes = _combine_indexes(cls_, indexes)
        result_events = _combine_events(cls_, events)
        try:
            result_nb_crud = nb_crud or cls_._get_nb_crud_type()
        except AttributeError:
            result_nb_crud = None

        class ConstructedClass(cls_):
            @classmethod
            def get_indexes(cls):
                return result_indexes

            @classmethod
            def get_events(cls):
                return result_events

            @classmethod
            def _get_nb_crud_type(cls):
                return result_nb_crud

        return type(cls_.__name__, (ConstructedClass,), {})

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
