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
import itertools
import threading

from dragonflow.utils import radix_tree


ANY = radix_tree.ANY
MISSING = None


class _IndexCache(object):
    '''A cache for a specific index of a model.

       This index class is responsible for keeping up-to-date key to object ID
       mapping, and providing ability to query this mapping.

       Internally a tree with sets on the leafs is used. We need a collection
       because we might have more than one object per key (e.g. many ports per
       topic. Set was chosen due to fast insert/delete but it forces us to
       store immutable objects so we resort to storing IDs (strings).

       The ID to object translation is done by model cache.
    '''

    def __init__(self, index):
        self._index = index
        self._tree = radix_tree.RadixTree(len(index))

        # We save ID->keys mapping for updating (object might have changed)
        # and deletion (object might contain just the ID)
        self._keys = collections.defaultdict(set)

    def delete(self, obj):
        keys = self._keys.pop(obj.id)

        for key in keys:
            self._tree.delete(key, obj.id)

    def update(self, obj):
        new_keys = set(self._get_keys(obj))
        old_keys = self._keys.get(obj.id, set())

        # Re-insert into cache only if key changed
        added_keys = new_keys - old_keys
        deleted_keys = old_keys - new_keys

        for key in added_keys:
            self._tree.set(key, obj.id)

        for key in deleted_keys:
            self._tree.delete(key, obj.id)

        self._keys[obj.id] = new_keys

    def get_all(self, obj):
        for key in self._get_keys(obj):
            for obj in self._tree.get_all(key):
                yield obj

    def _get_key_element(self, obj, key_element):
        path = key_element.split('.')
        extras = set()
        nodes = [obj]

        for p in path:
            new_nodes = []
            for node in nodes:
                attr = getattr(node, p)
                if isinstance(attr, list):
                    new_nodes.extend(attr)
                elif attr is None:
                    extras.add(MISSING)
                else:
                    new_nodes.append(attr)
            nodes = new_nodes

        return set(nodes).union(extras)

    def _get_keys(self, obj):
        keys = []
        for f in self._index:
            values = self._get_key_element(obj, f)
            keys.append(values)

        return itertools.product(*keys)


def _take_one(iterable):
    try:
        return next(iterable)
    except StopIteration:
        return None


class _ModelCache(object):
    '''A cache for all instances of a model

    This class stores all the instances (that were added to DbStore) of a
    specific model, and maintains up to date indexes for the elements to allow
    quick querying.
    '''

    def __init__(self, model):
        self._objs = {}
        self._indexes = {}
        self._id_index = model.get_indexes()['id']

        indexes = model.get_indexes()
        for index in indexes.values():
            if index == self._id_index:
                continue

            self._indexes[index] = _IndexCache(index)

    def _get_by_id(self, obj_id):
        return self._objs[obj_id]

    def delete(self, obj):
        for index in self._indexes.values():
            index.delete(obj)

        del self._objs[obj.id]

    def update(self, obj):
        for index in self._indexes.values():
            index.update(obj)

        self._objs[obj.id] = obj

    def get_one(self, obj, index):
        if index not in (None, self._id_index):
            keys = self.get_keys(obj, index)
            obj_id = _take_one(keys)

            if obj_id is not None and _take_one(keys) is not None:
                raise ValueError(_('More than one result available'))
        else:
            obj_id = obj.id

        try:
            return self._get_by_id(obj_id)
        except KeyError:
            return None

    def get_keys(self, obj, index):
        # No index, return all keys
        if index is None:
            return self._objs.keys()
        elif index == ('id',):
            return iter((obj.id,))
        else:
            return self._indexes[index].get_all(obj)

    def get_all(self, obj, index):
        ids = self.get_keys(obj, index)
        return (self._get_by_id(id_) for id_ in ids)


class DbStore2(object):
    def __init__(self):
        self._cache = {}

    def _get_cache(self, model):
        try:
            return self._cache[model]
        except KeyError:
            cache = _ModelCache(model)
            self._cache[model] = cache
            return cache

    def get_one(self, obj, index=None):
        """Retrieve an object from cache by ID or by a provided index. If
           several objects match the query, an ValueError is raised.

           >>> db_store.get(Lport(id='id1'))
           Lport(...)

           >>> db_store.get(Lport(unique_key=1),
                            index=Lport.get_indexes()['unique_key'])
           Lport(...)
        """
        model = type(obj)
        return self._get_cache(model).get_one(obj, index)

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
        return self.get_one(elem) == elem

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
