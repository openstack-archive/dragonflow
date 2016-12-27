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


class Namespace(object):
    '''A class that accepts keyword parameters on creation, and exposes access
       through attributes

       >>> ns = Namespace(a=1, b=2)
       >>> ns.a
       1
       >>> ns.b
       2
       >>> tuple(ns)
       (('a', 1), ('b', 2))

    '''
    def __init__(self, **kwargs):
        self._dict = {}

        for key, value in six.iteritems(kwargs):
            self._add_attr(key, value)

    def _add_attr(self, key, value):
        self._dict[key] = value

    def __iter__(self):
        for key, value in six.iteritems(self._dict):
            yield key, value

    def impose_over(self, other):
        for key, value in other:
            if key not in self._dict:
                self._add_attr(key, value)

    def __getattr__(self, name):
        if name in self._dict:
            return self._dict[name]
        raise AttributeError(name)

    def copy(self):
        return Namespace(**self._dict)
