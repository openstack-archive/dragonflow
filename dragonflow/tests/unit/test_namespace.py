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
from dragonflow.tests import base as tests_base
from dragonflow.utils import namespace


class TestNamespace(tests_base.BaseTestCase):
    def test_attribute_access(self):
        ns = namespace.Namespace(a=1, b=2)
        self.assertEqual(1, ns.a)
        self.assertEqual(2, ns.b)

    def test_attribute_iter(self):
        ns = namespace.Namespace(a=1, b=2)
        self.assertEqual({'a': 1, 'b': 2}, dict(iter(ns)))

    def test_impose(self):
        ns1 = namespace.Namespace(a=1, b=2)
        ns2 = namespace.Namespace(a=2, c=4)

        ns1.impose_over(ns2)
        self.assertEqual(1, ns1.a)
        self.assertEqual(2, ns1.b)
        self.assertEqual(4, ns1.c)
