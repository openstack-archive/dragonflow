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
import mock

from dragonflow.tests.fullstack import test_base
from dragonflow.tests.unit import test_app_base


class Test_API_NB(test_base.DFTestBase):

    def setUp(self):
        super(Test_API_NB, self).setUp()
        # NOTE: In this test class, we make changes directly on nb_api. It
        # tries to publish these changes. However, since this is not a
        # neutron server, the publisher isn't initialised. That throws an
        # (uninteresting) error
        publisher = mock.patch.object(self.nb_api, 'publisher')
        self.addCleanup(publisher.stop)
        publisher.start()

    def test_create_lswitch(self):
        fake_lswitch = copy.deepcopy(
            test_app_base.fake_logic_switch1.inner_obj)
        del fake_lswitch['unique_key']

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

    def test_create_lport(self):
        fake_lport = copy.deepcopy(
            test_app_base.fake_local_port1.inner_obj)
        del fake_lport['unique_key']
        fake_lport['lswitch_id'] = 'fake_switch1'
        self.nb_api.create_lport(**fake_lport)
        self.addCleanup(self.nb_api.delete_lport,
                        fake_lport['id'], fake_lport['topic'])
        lport = self.nb_api.get_logical_port(fake_lport['id'],
                                             fake_lport['topic'])
        self.assertIsNotNone(lport.get_unique_key())

        fake_lport1 = copy.deepcopy(fake_lport)
        fake_lport1['id'] = 'other_id'
        self.nb_api.create_lport(**fake_lport1)
        self.addCleanup(self.nb_api.delete_lport,
                        fake_lport1['id'], fake_lport1['topic'])
        lport1 = self.nb_api.get_logical_port(fake_lport1['id'],
                                              fake_lport1['topic'])
        self.assertIsNotNone(lport1.get_unique_key())

        self.assertNotEqual(lport.get_unique_key(),
                            lport1.get_unique_key())
