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
from dragonflow.db.models import LogicalPort, LogicalSwitch
from dragonflow.tests.unit import test_app_base


class TestDfController(test_app_base.DFAppTestBase):

    apps_list = "l2_ml2_app.L2App"

    def setUp(self):
        super(TestDfController, self).setUp()
        self.controller = DfLocalController('chassis1')
        self.controller.nb_api = mock.Mock()
        self.controller.db_store = mock.Mock()
        self.controller.vswitch_api = mock.Mock()
        self.controller.nb_api.get_lport_migration.return_value = {}

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

    def test_update_migration_flows(self):
        self.controller.nb_api.get_lport_migration.return_value = \
            {'migration': 'chassis1'}
        self.controller.db_store.get_lswitch.return_value = \
            self.lswitch1
        self.controller.vswitch_api.get_chassis_ofport.return_value = 3
        self.controller.vswitch_api.get_port_ofport_by_id.retrun_value = 2

        self.controller.update_migration_flows(self.lport1)
        self.lport1.set_external_value.assert_called_with('ofport', 2)
