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

from dragonflow.controller.df_local_controller import DfLocalController
from dragonflow.controller import dispatcher
from dragonflow.db.api_nb import LogicalPort, LogicalSwitch
from dragonflow.tests import base as tests_base


class TestDfController(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDfController, self).setUp()
        self.controller = DfLocalController('chassis1')

        self.controller.db_store = mock.Mock()
        self.controller.nb_api = mock.Mock()
        self.controller.vswitch_api = mock.Mock()
        self.controller.open_flow_app = mock.Mock()

        self.lport1_value = '''
            {
                "name": "lport",
                "chassis": "chassis1",
                "admin_state": "True",
                "ips": ["192.168.10.10"],
                "macs": ["112233445566"],
                "lswitch": "lswitch",
                "topic": "tenant1"
            }
            '''

        self.lswitch1_value = '''
            {
                "name": "lswitch1",
                "subnets": ["subnet1"]
            }
        '''

        self.lport1 = LogicalPort(self.lport1_value)
        self.lswitch1 = LogicalSwitch(self.lswitch1_value)

    def test_update_migration_flows(self, lport):
        self.controller.nb_api.get_lport_state.return_value = \
            {'state': 'chassis2'}
        self.controller.db_store.get_lswitch.return_value = \
            self.lswitch1
        self.controller.vswitch_api.get_chassis_ofport.return_value = 3
        self.controller.vswitch_api.get_port_ofport_by_id.retrun_value = 2

        self.controller.update_migration_flows.assert_call_with(
            self.lport1)