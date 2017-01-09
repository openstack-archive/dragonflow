# Copyright (c) 2015 OpenStack Foundation.
# All Rights Reserved.
#
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
import threading

import six


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


def _get_obj_key(obj, fields):
    """Extract key for a specific index (tuple of fields)

       >>> _get_obj_key(Lport(id='1', topic='2', name='foo'), ('topic', 'id'))
       ('2', '1')
    """
    return tuple(getattr(obj, f) for f in fields)


class DbStore2(object):
    def __init__(self):
        self._cache = collections.defaultdict(
            functools.partial(collections.defaultdict, dict),
        )

    def get(self, obj, index=None):
        """Retrieve an object from cache by ID or by a provided index"""
        model = type(obj)
        if index is None:
            index = model.get_indexes().id

        fields = _normalize_tuple(index)
        key = _get_obj_key(obj, fields)
        return self._cache[model][fields].get(key)

    def get_all(self, model, topic=None):
        """Get all objects of a specific model, or only those with a specific
           topic
        """
        index = _normalize_tuple(model.get_indexes().id)
        values = six.itervalue(self._cache[model][index].values())

        if topic is None:
            return values

        # FIXME implement by partial index lookup
        return (v for v in values if v.topic == topic)

    def get_keys(self, model, topic=None):
        index = _normalize_tuple(model.get_indexes().id_topic)
        values = six.iterkeys(self._cache[model][index])

        if topic is None:
            return (i for i, t in values)
        else:
            return (i for i, t in values if t == topic)

    def delete(self, obj):
        """Deletes the object provided from the cache, by removing it from alll
           the indexes, a partial object can be provided, since we retrieve the
           stored object by ID from the cache (to make sure we remove it by
           correct keys)

           >>> db_store.delete(Lport(id=lport_id))
        """
        obj = self.get(obj)  # Get the full object stored in the cache

        if obj is None:
            return

        model = type(obj)

        for name, fields in model.get_indexes():
            fields = _normalize_tuple(fields)
            index_cache = self._cache[model][fields]
            key = _get_obj_key(obj, fields)
            del index_cache[key]

    def update(self, obj):
        """Sets or updates an object int the cache. This will remove the older
           version from all the indexes and populate them with the new object
        """
        self.delete(obj)

        model = type(obj)

        for _, fields in model.get_indexes():
            fields = _normalize_tuple(fields)
            index_cache = self._cache[model][fields]
            key = _get_obj_key(obj, fields)
            index_cache[key] = obj


_instance = None
_instance_lock = threading.Lock()


def get():
    global _instance

    with _instance_lock:
        if _instance is None:
            _instance = DbStore2()
        return _instance
