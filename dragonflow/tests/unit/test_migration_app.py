# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import copy

import mock

from dragonflow import conf as cfg
from dragonflow.db.models import migration
from dragonflow.tests.unit import test_app_base


class TestMigrationApp(test_app_base.DFAppTestBase):
    apps_list = ["migration"]

    def test_update_migration_flows(self):
        cfg.CONF.set_override('host', 'fake-local-host')
        lport = copy.deepcopy(test_app_base.fake_local_port1)
        fake_lswitch = test_app_base.fake_logic_switch1
        migration_obj = migration.Migration(
                id=lport.id, dest_chassis='fake-local-host', lport=lport,
                status=migration.MIGRATION_STATUS_SRC_UNPLUG)
        self.controller.nb_api.get.return_value = lport

        self.controller.db_store.update(fake_lswitch)
        self.controller.db_store.update(lport)
        self.controller.vswitch_api.get_chassis_ofport.return_value = 3
        self.controller.vswitch_api.get_port_ofport_by_id.retrun_value = 2

        mock_update_patch = mock.patch.object(
                self.controller.db_store,
                'update',
                side_effect=self.controller.db_store.update
        )
        mock_update = mock_update_patch.start()
        self.addCleanup(mock_update_patch.stop)

        mock_emit_created_patch = mock.patch.object(
                lport, 'emit_bind_local')
        mock_emit_created = mock_emit_created_patch.start()
        self.addCleanup(mock_emit_created_patch.stop)

        self.controller.update(migration_obj)
        self.assertEqual([mock.call(migration_obj), mock.call(lport)],
                         mock_update.call_args_list)
        mock_emit_created.assert_called_with()
