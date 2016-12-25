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

import six

from jsonmodels import fields
from jsonmodels import models

from dragonflow._i18n import _LE


class Namespace(object):
    '''A class that accepts keyword parameters on creation, e.g.
       ns = Namespace(a=1, b=2)
       and exposes them as attributes:
       ns.a => 1, ns.b => 2
    '''
    def __init__(self, **kwargs):
        self._dict = {}

        for key, value in six.iteritems(kwargs):
            self._add_attr(key, value)

    def _add_attr(self, key, value):
        self._dict[key] = value
        setattr(self, key, value)

    def __iter__(self):
        for key, value in six.iteritems(self._dict):
            yield key, value

    def impose_over(self, other):
        for key, value in other:
            if key not in self._dict:
                self._add_attr(key, value)


def _normalize(obj):
    '''Receives an object or a sequence, if we got an object, wrap it in a
       tuple of one and return it, otherwise return the sequence
    '''
    try:
        if isinstance(obj, str):
            return (obj,)
        return tuple(obj)
    except TypeError:
        return (obj,)


# O(a lot) db store implementation
class MockDbStore(object):
    def __init__(self):
        self._store = {}

    def _extract_key(self, obj, index):
        return tuple(getattr(obj, field) for field in index)

    def get(self, model, index, key):
        index = _normalize(index)
        key = _normalize(key)

        for obj in self._store.get(model, ()):
            if self._extract_key(obj, index) == key:
                return obj

        raise KeyError(key)

    def store(self, obj):
        self._store.setdefault(type(obj), []).append(obj)


db_store = MockDbStore()


def _combine_indexes(base_class, new_indexes):
    result = Namespace()

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


def construct_nb_db_model(cls_=None, indexes=None, events=None, nb_crud=None):
    def decorator(cls_):
        # Compute results ahead of time
        result_indexes = _combine_indexes(cls_, indexes)
        result_events = _combine_events(cls_, events)
        result_nb_crud = nb_crud or cls_.get_nb_crud()

        class ConstructedClass(cls_):
            @classmethod
            def get_indexes(cls):
                return result_indexes

            @classmethod
            def get_events(cls):
                return result_events

            @classmethod
            def get_nb_crud(cls):
                return result_nb_crud

        return type(cls_.__name__, (ConstructedClass,), {})

    if cls_ is None:
        return decorator
    else:
        return decorator(cls_)


class classattr(object):
    def __init__(self, attr):
        self.attr = attr

    def __get__(self, inst, cls):
        if inst is None:
            return self.attr
        else:
            raise AttributeError(
                _LE('Accessing class-only attribute through instance'))


class RefWrapper(object):
    def __init__(self, model, key, lazy=True):
        self._inst = None
        self._model = model
        self._key = key

        self._index_field = 'id'  # FIXME
        self._proxied_fields = set(n for n, _ in model.iterate_over_fields())
        self._proxied_fields.discard(self._index_field)

        if not lazy:
            self._instance

    def _fetch(self):
        return db_store.get(
            self._model, self._model.get_indexes().id, self._key)

    @property
    def _instance(self):
        if self._inst is None:
            self._inst = self._fetch()
        return self._inst

    def __getattr__(self, name):
        if name in self._proxied_fields:
            return getattr(self._instance, name)
        elif name == self._index_field:
            return self._key
        else:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name.startswith('_') or name not in self._proxied_fields:
            super(RefWrapper, self).__setattr__(name, value)
        else:
            setattr(self._instance, name, value)

    def get_field(self, name):
        return getattr(self, name)


class Ref(fields.BaseField):
    def __init__(self, model, lazy=True, *args, **kwargs):
        super(Ref, self).__init__(*args, **kwargs)
        self._model = model
        self._lazy = lazy

    def validate(self, value):
        pass

    def __set__(self, instance, key):
        super(Ref, self).__set__(
            instance, RefWrapper(self._model, key, lazy=self._lazy))


@construct_nb_db_model(
    indexes=Namespace(id='id'),
    events=('created', 'updated', 'deleted'),
    nb_crud=object(),
)
class NbDbModelBase(models.Base):
    id = fields.StringField(required=True)


@construct_nb_db_model(indexes=Namespace(id_topic=('id', 'topic')))
class NbDbModelWithTopic(NbDbModelBase):
    topic = fields.StringField(required=True)
