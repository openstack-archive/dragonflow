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

import copy

from dragonflow.tests.fullstack import test_base
from dragonflow.tests.unit import test_app_base


class Test_API_NB(test_base.DFTestBase):

    def test_allocate_tunnel_key(self):
        key1 = self.nb_api.allocate_tunnel_key()
        key2 = self.nb_api.allocate_tunnel_key()
        self.assertNotEqual(key1, key2)

    def test_create_lswitch(self):
        fake_lswitch = test_app_base.fake_logic_switch1.inner_obj
        self.nb_api.create_lswitch(**fake_lswitch)
        self.addCleanup(self.nb_api.delete_lswitch,
                        fake_lswitch['id'], fake_lswitch['topic'])
        lswitch = self.nb_api.get_lswitch(fake_lswitch['id'],
                                          fake_lswitch['topic'])
        self.assertIsNotNone(lswitch.get_unique_key())

        fake_lswitch1 = copy.deepcopy(fake_lswitch)
        fake_lswitch1['id'] = 'other_id'
        self.nb_api.create_lswitch(**fake_lswitch1)
        self.addCleanup(self.nb_api.delete_lswitch,
                        fake_lswitch1['id'], fake_lswitch1['topic'])
        lswitch1 = self.nb_api.get_lswitch(fake_lswitch1['id'],
                                          fake_lswitch1['topic'])
        self.assertIsNotNone(lswitch1.get_unique_key())

        self.assertNotEqual(lswitch.get_unique_key(),
                            lswitch1.get_unique_key())
