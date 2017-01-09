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
import threading

import six

from dragonflow.utils import radix_tree


ANY = radix_tree.ANY
MISSING = None


class _IndexCache(object):
    '''A cache for a specific index of a model.

       This index class is responsible for keeping up to date key to object ID
       mapping, and providing ability to query this mapping.

       Due to the fact that objects themselves are mutable, only store their
       ID. ID to object translation is done by the model cache.
    '''

    def __init__(self, index):
        self._index = index
        self._tree = radix_tree.RadixTree(len(index))

        # We save ID->key mapping for updating (object might have changed)
        # and deletion (object might contain just the ID)
        self._keys = {}

    def delete(self, obj):
        key = self._keys.pop(obj.id)
        self._tree.delete(key, obj.id)

    def update(self, obj):
        new_key = self._get_key(obj)
        old_key = self._keys.get(obj.id)

        # Re-insert into cache only if key changed
        if old_key == new_key:
            return

        if old_key is not None:
            self.delete(obj)

        self._keys[obj.id] = new_key
        self._tree.set(new_key, obj.id)

    def get_all(self, obj):
        return self._tree.get_all(self._get_key(obj))

    def _get_key(self, obj):
        key = []
        for f in self._index:
            if obj.field_is_set(f):
                value = getattr(obj, f)
            else:
                value = MISSING

            key.append(value)

        return tuple(key)


class _ModelCache(object):
    def __init__(self, model):
        self._objs = {}
        self._indexes = {}

        indexes = model.get_indexes()
        for index in six.itervalues(indexes):
            if index == indexes['id']:
                continue

            self._indexes[index] = _IndexCache(index)

    def _get_by_id(self, obj_id):
        return self._objs[obj_id]

    def delete(self, obj):
        for index in six.itervalues(self._indexes):
            index.delete(obj)

        self._objs.pop(obj.id)

    def update(self, obj):
        for index in six.itervalues(self._indexes):
            index.update(obj)

        self._objs[obj.id] = obj

    def get(self, obj, index):
        if index in (None, ('id',)):
            obj_id = obj.id
        else:
            try:
                # Return the first one if there are several matches
                obj_id = next(self.get_all(obj, index))
            except StopIteration:
                raise KeyError()
        try:
            return self._get_by_id(obj_id)
        except KeyError:
            return None

    def get_keys(self, obj, index):
        # No index, return all keys
        if index is None:
            return six.iterkeys(self._objs)
        elif index == ('id',):
            return (obj.id,)
        else:
            return self._indexes[index].get_all(obj)

    def get_all(self, obj, index):
        ids = self.get_keys(obj, index)
        return (self._get_by_id(id_) for id_ in ids)


class DbStore2(object):
    def __init__(self):
        self._cache = {}

    def _get_cache(self, model):
        if model not in self._cache:
            self._cache[model] = _ModelCache(model)
        return self._cache[model]

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
        return self._get_cache(model).get(obj, index)

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
        else:
            model = type(obj)

        return self._get_cache(model).get_all(obj, index)

    def get_keys(self, obj, index=None):
        '''Returns IDs for all objects matching the query. If index is ommited,
           we assume result should contain all object of the model.

           >>> db_store.get_keys(Lport(topic='topic1'),
                                 index=Lport.get_indexes()['topic'])
           ('id1', 'id2', 'id3', ...)
        '''
        if type(obj) == type:
            model = obj
            obj = model()
        else:
            model = type(obj)

        return tuple(self._get_cache(model).get_keys(obj, index))

    def delete(self, obj):
        """Deletes the object provided from the cache, by removing it from all
           the indexes, a partial object can be provided, since we retrieve the
           stored object by ID from the cache (to make sure we remove it by
           correct keys)

           >>> db_store.delete(Lport(id=lport_id))
        """
        self._get_cache(type(obj)).delete(obj)

    def update(self, obj):
        """Sets or updates an object int the cache. This will remove the older
           version from all the indexes and populate them with the new object
        """
        self._get_cache(type(obj)).update(obj)

    def __contains__(self, elem):
        return self.get(elem) == elem

    def get_all_by_topic(self, model, topic=None):
        return self.get_all(
            model(topic=topic),
            index=model.get_indexes()['topic'],
        )

    def get_keys_by_topic(self, model, topic=None):
        return self.get_keys(
            model(topic=topic),
            index=model.get_indexes()['topic'],
        )


_instance = None
_instance_lock = threading.Lock()


def get_instance():
    global _instance

    with _instance_lock:
        if _instance is None:
            _instance = DbStore2()
        return _instance
