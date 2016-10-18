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

from dragonflow.tests.fullstack import test_base


class Test_API_NB(test_base.DFTestBase):

    def test_allocate_tunnel_key(self):
        key1 = self.nb_api.allocate_tunnel_key()
        key2 = self.nb_api.allocate_tunnel_key()
        self.assertNotEqual(key1, key2)
