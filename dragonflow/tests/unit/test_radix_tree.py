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
from dragonflow.utils import radix_tree


ANY = radix_tree.ANY


class TestRadixTree(tests_base.BaseTestCase):
    def test_create(self):
        for i in range(10):
            radix_tree.RadixTree(i)

    def test_store(self):
        rt = radix_tree.RadixTree(2)
        rt.set((1, 2), object())

    def test_retrieve_full_index(self):
        rt = radix_tree.RadixTree(2)
        rt.set((1, 2), True)
        rt.set((1, 2), False)
        self.assertItemsEqual({True, False}, rt.get_all((1, 2)))

    def test_retrieve_full_index_with_none(self):
        rt = radix_tree.RadixTree(2)
        rt.set((None, 2), False)
        self.assertItemsEqual({False}, rt.get_all((None, 2)))

    def test_retrieve_partial_index(self):
        rt = radix_tree.RadixTree(2)
        rt.set((1, 2), True)
        rt.set((1, 3), False)
        self.assertItemsEqual({True, False}, rt.get_all((1, ANY)))

    def test_retrieve_partial_index2(self):
        rt = radix_tree.RadixTree(4)
        rt.set((1, 1, 1, 2), True)
        rt.set((1, 2, 3, 2), False)
        rt.set((1, 2, None, 2), False)
        self.assertItemsEqual((True, False, False),
                              rt.get_all((1, ANY, ANY, 2)))

    def test_delete(self):
        rt = radix_tree.RadixTree(2)
        rt.set((1, 2), True)
        rt.set((1, 2), False)
        rt.delete((1, 2), True)
        self.assertItemsEqual({False}, rt.get_all((1, 2)))
