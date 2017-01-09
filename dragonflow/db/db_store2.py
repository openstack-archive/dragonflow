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
import threading

import six

from dragonflow.utils import radix_tree


ANY = radix_tree.ANY
MISSING = None


class IndexCache(object):
    '''Index for a model class, implemented using a radix tree'''
    def __init__(self, index):
        self._index = index
        self._tree = radix_tree.RadixTree(len(index))
        self._keys = {}

    def set(self, obj):
        '''Stores an object in the index according to the fields'''
        key = self._get_key(obj)
        self._keys[obj] = key
        self._tree.set(key, obj)

    def _get_key(self, obj):
        key = []
        for f in self._index:
            if obj.field_is_set(f):
                value = getattr(obj, f)
            else:
                value = MISSING

            key.append(value)

        return tuple(key)

    def get_all(self, obj):
        return self._tree.get_all(self._get_key(obj))

    def get(self, obj):
        key = self._get_key(obj)
        try:
            return next(iter(self._tree.get_all(key)))
        except StopIteration:
            raise KeyError(key)

    def delete(self, obj):
        key = self._keys.pop(obj)
        self._tree.delete(key, obj)


class DbStore2(object):
    def __init__(self):
        self._cache = collections.defaultdict(dict)

    def _get_index_cache(self, model, index):
        model_cache = self._cache[model]

        index_cache = model_cache.get(index)
        if index_cache is None:
            index_cache = IndexCache(index)
            model_cache[index] = index_cache

        return index_cache

    def get(self, obj, index=None):
        """Retrieve an object from cache by ID or by a provided index. If
           several objects match the query, first one is returned

           >>> db_store.get(Lport(id='id1'))
           Lport(...)

           >>> db_store.get(Lport(unique_key=1),
                            index=Lport.get_indexes()['unique_key'])
           Lport(...)
        """

        model = type(obj)
        if index is None:
            index = model.get_indexes()['id']

        try:
            return self._get_index_cache(model, index).get(obj)
        except KeyError:
            return None

    def get_all(self, obj, index=None):
        """Get all objects of a specific model, matching a specific index
           lookup.

            >>> db_store.get_all(Lport(topic='topic1'),
                                 index=Lport.get_indexes()['topic'])
            (Lport(...), Lport(...), ...)
        """

        if type(obj) == type:
            model = obj
            obj = model()

            # No keys specified, we effectively want all items
            index = model.get_indexes()['all']
        else:
            model = type(obj)

        if index is None:
            index = model.get_indexes()['id']

        return self._get_index_cache(model, index).get_all(obj)

    def get_all_by_topic(self, model, topic):
        return self.get_all(
            model(topic=topic),
            index=model.get_indexes()['topic'],
        )

    def get_keys(self, obj, index=None):
        #FIXME inefficient, implement with get_keys
        return [o.id for o in self.get_all(obj, index=index)]

    def get_keys_by_topic(self, model, topic=None):
        return self.get_keys(
            model(topic=topic),
            index=model.get_indexes()['topic'],
        )

    def delete(self, obj):
        """Deletes the object provided from the cache, by removing it from all
           the indexes, a partial object can be provided, since we retrieve the
           stored object by ID from the cache (to make sure we remove it by
           correct keys)

           >>> db_store.delete(Lport(id=lport_id))
        """
        obj = self.get(obj)  # Get the full object stored in the cache

        if obj is None:
            return

        model = type(obj)

        for _, index in six.iteritems(model.get_indexes()):
            self._get_index_cache(model, index).delete(obj)

    def update(self, obj):
        """Sets or updates an object int the cache. This will remove the older
           version from all the indexes and populate them with the new object
        """
        self.delete(obj)

        model = type(obj)

        for _, index in six.iteritems(model.get_indexes()):
            self._get_index_cache(model, index).set(obj)

    def __contains__(self, elem):
        return self.get(elem) == elem


_instance = None
_instance_lock = threading.Lock()


def get_instance():
    global _instance

    with _instance_lock:
        if _instance is None:
            _instance = DbStore2()
        return _instance
