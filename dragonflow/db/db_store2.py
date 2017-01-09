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

from dragonflow._i18n import _LE


class RadixTree(object):
    def __init__(self, depth):
        self._depth = depth

        tree_type = dict
        for _ in range(1, depth):
            tree_type = functools.partial(collections.defaultdict, tree_type)

        self._root = tree_type()

    def set(self, path, value):
        node, key = self._traverse_to_leaf(path)
        node[key] = value

    def delete(self, path):
        node, key = self._traverse_to_leaf(path)
        del node[key]

    def _traverse_to_leaf(self, path):
        non_last_items = path[:-1]
        last_item = path[-1]

        node = self._root
        for item in non_last_items:
            node = node[item]

        return node, last_item

    def get_all(self, path):
        node = self._root

        if len(path) > 0:
            node, key = self._traverse_to_leaf(path)
            node = node[key]
            if len(path) == self._depth:
                return (node,)

        leaf_depth = self._depth - len(path)

        values = node.values()
        for _ in range(leaf_depth - 1):
            deeper_values = []
            for value in values:
                deeper_values.extend(value.values())
            values = deeper_values

        return values


class Index(object):
    def __init__(self, index):
        self._index = index
        self._tree = RadixTree(len(index))

    def set(self, obj):
        key = tuple(getattr(obj, f) for f in self._index)
        self._tree.set(key, obj)

    def _get_key(self, obj):
        key = []
        for f in self._index:
            try:
                value = getattr(obj, f)
            except RuntimeError:
                value = None

            if value is None:
                break

            key.append(value)

        return key

    def get_all(self, obj):
        key = self._get_key(obj)
        return self._tree.get_all(key)

    def get(self, obj):
        key = self._get_key(obj)
        if len(key) < len(self._index):
            raise ValueError(_LE('Object does not contain full key'))
        try:
            return next(iter(self._tree.get_all(key)))
        except IndexError:
            raise KeyError(key)

    def delete(self, obj):
        key = self._get_key(obj)
        if len(key) < len(self._index):
            raise ValueError(_LE('Object does not contain full key'))

        self._tree.delete(key)


class DbStore2(object):
    def __init__(self):
        self._cache = collections.defaultdict(dict)

    def _get_index_cache(self, model, index):
        model_cache = self._cache[model]

        index_cache = model_cache.get(index)
        if index_cache is None:
            index_cache = Index(index)
            model_cache[index] = index_cache

        return index_cache

    def get(self, obj, index=None):
        """Retrieve an object from cache by ID or by a provided index. If
           several objects match the query, first one is returned

           >>> db_store.get(Lport(id='id1'))
           Lport(...)

           >>> db_store.get(Lport(unique_key=1),
                            index=Lport.get_indexes().unique_key)
           Lport(...)
        """

        model = type(obj)
        if index is None:
            index = model.get_indexes().id

        try:
            return self._get_index_cache(model, index).get(obj)
        except KeyError:
            return None

    def get_all(self, obj, index=None):
        """Get all objects of a specific model, matching a specific index
           lookup.

            >>> db_store.get_all(Lport(topic='topic1'),
                                 index=Lport.get_indexes().topic_id)
            (Lport(...), Lport(...), ...)
        """

        if type(obj) == type:
            model = obj
            obj = model()
        else:
            model = type(obj)

        if index is None:
            index = model.get_indexes().id

        return self._get_index_cache(model, index).get_all(obj)

    def get_all_by_topic(self, model, topic):
        return self.get_all(
            model(topic=topic),
            index=model.get_indexes().topic_id,
        )

    def get_keys(self, obj, index=None):
        #FIXME inefficient, should implement with get_keys()
        return [o.id for o in self.get_all(obj, index=index)]

    def get_keys_by_topic(self, model, topic=None):
        return self.get_keys(
            model(topic=topic),
            index=model.get_indexes().topic_id,
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

        for _, index in model.get_indexes():
            self._get_index_cache(model, index).delete(obj)

    def update(self, obj):
        """Sets or updates an object int the cache. This will remove the older
           version from all the indexes and populate them with the new object
        """
        self.delete(obj)

        model = type(obj)

        for _, index in model.get_indexes():
            self._get_index_cache(model, index).set(obj)

    def __contains__(self, elem):
        return self.get(elem) == elem


_instance = None
_instance_lock = threading.Lock()


def get():
    global _instance

    with _instance_lock:
        if _instance is None:
            _instance = DbStore2()
        return _instance
