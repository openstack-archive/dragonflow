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
import itertools


ANY = None


class RadixTree(object):
    '''A constant depth radix tree written (originally) for indexing in DbStore

    This implementation stores several (or none) items for each path

    '''
    def __init__(self, depth):
        self._depth = depth

        tree_type = set
        for _ in range(depth):
            tree_type = functools.partial(collections.defaultdict, tree_type)

        self._root = tree_type()

    def set(self, path, value):
        '''Stores value at given path
        '''
        self._traverse_to_leaf_set(path).add(value)

    def delete(self, path, value):
        '''Deletes a value from a given path'''
        traces = []
        node = self._root

        # Clean the dicts if path now empty
        for key in path:
            traces.append((key, node))
            node = node[key]

        node.discard(value)

        for key, node in reversed(traces):
            if key in node:
                break

            del node[key]

    def _traverse_to_leaf_set(self, path):
        node = self._root
        for item in path:
            node = node[item]

        return node

    def get_all(self, path):
        '''Get all items matching the path provided, if None is present in the
        path, it is treated as a wildcard

        >>> t.get_all((None, None,))
        (<all values>)


        >>> t.get_all((1, 2))
        (<All values at path 1, 2>)
        '''
        nodes = [self._root]

        for segment in path:
            next_nodes = []

            for node in nodes:
                if segment is ANY:
                    next_nodes.extend(node.values())
                else:
                    if segment in node:
                        next_nodes.append(node[segment])

            nodes = next_nodes

        return itertools.chain(*nodes)
