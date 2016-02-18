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

from neutron.tests import base as tests_base

from dragonflow.controller import df_local_controller
from dragonflow.controller import topology
from dragonflow.controller import dispatcher
from dragonflow.db import db_store


class TestTopology(tests_base.BaseTestCase):

    def setUp(self):
        super(TestTopology, self).setUp()

        controller_spec = [
                'get_open_flow_app',
                'get_nb_api',
                'get_db_store',
                'get_vswitch_api',
                'get_chassis_name',
        ]

        self.mock_controller = mock.Mock(spec=controller_spec)
        self.topology = topology.Topology(self.controller)

    def test_lport_updated(self):
        self.topology.lport_deleted(1)

