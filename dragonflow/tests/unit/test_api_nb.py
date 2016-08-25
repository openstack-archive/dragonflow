# Copyright (c) 2016 OpenStack Foundation.
# All Rights Reserved.
#
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
from oslo_serialization import jsonutils

from dragonflow.db import api_nb
from dragonflow.tests import base as tests_base


class TestApiNb(tests_base.BaseTestCase):

    def setUp(self):
        super(TestApiNb, self).setUp()
        self.driver = mock.MagicMock()
        self.api_nb = api_nb.NbApi(self.driver)

    def _setup_fake_lrouter(self):
        empty_router = {'topic': 'router_topic',
                        'version': 'fake_version',
                        'ports': []}
        router_port = {'id': 'fake_id',
                       'lrouter': 'fake_router',
                       'lswitch': 'fake_switch',
                       'topic': 'port_topic'}
        router_with_port = copy.deepcopy(empty_router)
        router_with_port['ports'].append(router_port)
        return empty_router, router_with_port

    def test_add_lrouter_port(self):
        original_router, expect_router = self._setup_fake_lrouter()
        self.driver.get_key.return_value = jsonutils.dumps(original_router)
        self.api_nb.add_lrouter_port('fake_id', 'fake_router',
                                     'fake_switch', 'port_topic',
                                     router_version='fake_version')
        # Router should be retrieved without tenant/topic.
        self.driver.get_key.assert_called_with('lrouter', 'fake_router')
        self.driver.set_key.assert_called_with(
            'lrouter', 'fake_router',
            jsonutils.dumps(expect_router), 'router_topic')

    def test_delete_lrouter_port(self):
        expect_router, original_router = self._setup_fake_lrouter()
        self.driver.get_key.return_value = jsonutils.dumps(original_router)
        self.api_nb.delete_lrouter_port('fake_id', 'fake_router',
                                        'port_topic',
                                        router_version='fake_version')
        # Router should be retrieved without tenant/topic.
        self.driver.get_key.assert_called_with('lrouter', 'fake_router')
        self.driver.set_key.assert_called_with(
            'lrouter', 'fake_router',
            jsonutils.dumps(expect_router), 'router_topic')
