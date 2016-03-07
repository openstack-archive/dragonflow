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

import mock

from oslo_config import cfg

from dragonflow.controller import dispatcher
from dragonflow.db import db_store
from dragonflow.tests import base as tests_base


class TestDfController(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDfController, self).setUp()
        dispatcher.AppDispatcher = mock.Mock()
        db_store.DbStore = mock.Mock()
        cfg.CONF = mock.Mock()
        self.controller = mock.Mock()
        self.controller.nb_api = mock.Mock()
        self.controller.vswitch_api = mock.Mock()

    def test_something(self):
        pass
