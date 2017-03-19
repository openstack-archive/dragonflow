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

from dragonflow.db import models as db_models
from dragonflow.db.models import l2
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
        fake_lswitch = l2.LogicalSwitch(id='test_lswitch0',
                                        topic='test_tenant1')

        self.nb_api.create(fake_lswitch)
        lean_fake_lswitch = l2.LogicalSwitch(id=fake_lswitch.id,
                                             topic=fake_lswitch.topic)
        self.addCleanup(self.nb_api.delete, lean_fake_lswitch)
        lswitch = self.nb_api.get(lean_fake_lswitch)
        self.assertIsNotNone(lswitch.unique_key)

        fake_lswitch1 = l2.LogicalSwitch(id='test_lswitch1',
                                         topic='test_tenant1')
        self.nb_api.create(fake_lswitch1)
        lean_fake_lswitch1 = l2.LogicalSwitch(id=fake_lswitch1.id,
                                              topic=fake_lswitch1.topic)
        self.addCleanup(self.nb_api.delete, lean_fake_lswitch1)
        lswitch1 = self.nb_api.get(lean_fake_lswitch1)
        self.assertIsNotNone(lswitch1.unique_key)

        self.assertNotEqual(lswitch.unique_key, lswitch1.unique_key)

    def test_create_lport(self):
        fake_lport = l2.LogicalPort(id='test_lport0', topic='test_tenant1')
        self.nb_api.create(fake_lport)
        self.addCleanup(self.nb_api.delete, fake_lport)
        lport = self.nb_api.get(fake_lport)
        self.assertIsNotNone(lport.get_unique_key())

        fake_lport1 = copy.deepcopy(fake_lport)
        fake_lport1['id'] = 'other_id'
        self.nb_api.create(fake_lport1)
        self.addCleanup(self.nb_api.delete, fake_lport1)
        lport1 = self.nb_api.get(fake_lport1)
        self.assertIsNotNone(lport1.get_unique_key())

        self.assertNotEqual(lport.get_unique_key(),
                            lport1.get_unique_key())

    def test_create_lrouter(self):
        fake_lrouter = copy.deepcopy(
            test_app_base.fake_logic_router1.inner_obj)
        fake_lrouter.pop('unique_key', None)
        self.nb_api.create_lrouter(**fake_lrouter)
        self.addCleanup(self.nb_api.delete_lrouter,
                        fake_lrouter['id'], fake_lrouter['topic'])
        lrouter = self.nb_api.get_router(fake_lrouter['id'],
                                         fake_lrouter['topic'])
        self.assertIsNotNone(lrouter.get_unique_key())

        fake_lrouter1 = copy.deepcopy(fake_lrouter)
        fake_lrouter1['id'] = 'other_id'
        self.nb_api.create_lrouter(**fake_lrouter1)
        self.addCleanup(self.nb_api.delete_lrouter,
                        fake_lrouter1['id'], fake_lrouter1['topic'])
        lrouter1 = self.nb_api.get_router(fake_lrouter1['id'],
                                          fake_lrouter1['topic'])
        self.assertIsNotNone(lrouter1.get_unique_key())

        self.assertNotEqual(lrouter.get_unique_key(),
                            lrouter1.get_unique_key())

    def test_create_listener(self):
        # prepare
        fake_listener1 = db_models.Listener("{}")
        fake_listener1.inner_obj = {"id": "fake_host1",
                                    "timestamp": 1,
                                    "ppid": -1}

        fake_listener2 = db_models.Listener("{}")
        fake_listener2.inner_obj = {"id": "fake_host2",
                                    "timestamp": 2,
                                    "ppid": -2}

        # test creating
        self.nb_api.create_neutron_listener('fake_host1',
                                            timestamp=1,
                                            ppid=-1)
        self.nb_api.create_neutron_listener('fake_host2',
                                            timestamp=2,
                                            ppid=-2)

        listeners = self.nb_api.get_all_neutron_listeners()
        self.assertIn(fake_listener1, listeners)
        self.assertIn(fake_listener2, listeners)

        # test updating timestamp
        self.nb_api.update_neutron_listener('fake_host1',
                                            timestamp=11)
        listener1 = self.nb_api.get_neutron_listener('fake_host1')
        self.assertEqual(listener1.get_timestamp(), 11)
        self.assertEqual(listener1.get_ppid(), -1)

        # test updating timestamp and ppid
        self.nb_api.update_neutron_listener('fake_host2',
                                            timestamp=22,
                                            ppid=-22)
        listener2 = self.nb_api.get_neutron_listener('fake_host2')
        self.assertEqual(listener2.get_timestamp(), 22)
        self.assertEqual(listener2.get_ppid(), -22)

        # test deleting
        self.nb_api.delete_neutron_listener('fake_host1')
        self.nb_api.delete_neutron_listener('fake_host2')
        listener1 = self.nb_api.get_neutron_listener('fake_host1')
        listener2 = self.nb_api.get_neutron_listener('fake_host2')
        self.assertIsNone(listener1)
        self.assertIsNone(listener2)
