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

from dragonflow.common import constants
from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.db import db_store
from dragonflow.db import db_store2
from dragonflow.db import model_proxy
from dragonflow.db.models import core
from dragonflow.tests.unit import test_app_base


class DfLocalControllerTestCase(test_app_base.DFAppTestBase):

    apps_list = "l2_app.L2App"

    @mock.patch.object(ryu_base_app.RyuDFAdapter, 'notify_ovs_sync_finished')
    def test_ovs_sync_finished(self, mock_notify):
        self.controller.ovs_sync_finished()
        mock_notify.assert_called_once()

    @mock.patch.object(ryu_base_app.RyuDFAdapter, 'notify_ovs_sync_started')
    def test_ovs_sync_started(self, mock_notify):
        self.controller.ovs_sync_started()
        mock_notify.assert_called_once()

    @mock.patch.object(df_local_controller.DfLocalController,
                       '_delete_lport_instance')
    @mock.patch.object(db_store2.DbStore2, 'get_all')
    @mock.patch.object(db_store2.DbStore2, 'delete')
    def test_delete_chassis(self, mock_db_store2_delete,
                            mock_get_ports, mock_delete_lport):
        lport_id = 'fake_lport_id'
        chassis = core.Chassis(id='fake_chassis_id')
        lport = mock.Mock()
        lport.id = lport_id
        mock_get_ports.return_value = [lport]

        self.controller.delete(chassis)
        mock_delete_lport.assert_called_once_with(lport)
        mock_db_store2_delete.assert_called_once_with(chassis)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_update_active_port')
    @mock.patch.object(db_store.DbStore, 'update_active_port')
    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store.DbStore, 'get_active_port')
    def test_update_activeport(self, mock_get_active, mock_get_one,
                               mock_update, mock_notify):
        active_port = mock.Mock()
        active_port.get_id.return_value = 'fake_id'
        active_port.get_topic.return_value = 'fake_topic'
        active_port.get_detected_lport_id.return_value = 'fake_lport_id'
        mock_get_active.return_value = None
        mock_update.return_value = None

        mock_get_one.return_value = None
        self.assertIsNone(self.controller.update_activeport(active_port))
        mock_notify.assert_not_called()

        lport = mock.Mock()
        mock_get_one.return_value = lport
        self.assertIsNone(self.controller.update_activeport(active_port))
        mock_notify.assert_called_once_with(active_port, None)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_remove_active_port')
    @mock.patch.object(db_store.DbStore, 'delete_active_port')
    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store.DbStore, 'get_active_port')
    def test_delete_activeport(self, mock_get_active, mock_get_one,
                               mock_delete, mock_notify):
        active_port = mock.Mock()
        active_port.get_topic.return_value = 'fake_topic'
        active_port.get_detected_lport_id.return_value = 'fake_lport_id'
        mock_get_active.return_value = None

        self.assertIsNone(self.controller.delete_activeport('fake_id'))
        mock_notify.assert_not_called()

        mock_get_active.return_value = active_port
        mock_delete.return_value = None
        lport = mock.Mock()
        mock_get_one.return_value = lport
        self.assertIsNone(self.controller.delete_activeport('fake_id'))
        mock_notify.assert_called_once_with(active_port)

    def test_register_chassis(self):
        cfg.CONF.set_override('external_host_ip',
                              '172.24.4.100',
                              group='df')
        self.controller.register_chassis()
        expected_chassis = core.Chassis(
            id=self.controller.chassis_name,
            ip=self.controller.ip,
            external_host_ip="172.24.4.100",
            tunnel_types=self.controller.tunnel_types,
        )

        self.assertIn(expected_chassis, self.controller.db_store2)
        self.nb_api.update.assert_called_once_with(expected_chassis)

    def test_update_migration_flows(self):
        self.controller.nb_api.get_lport_migration.return_value = \
            {'migration': 'fake_host'}
        lport = test_app_base.fake_local_port1
        fake_lswitch = test_app_base.fake_logic_switch1

        self.controller.db_store2.update(fake_lswitch)
        self.controller.vswitch_api.get_chassis_ofport.return_value = 3
        self.controller.vswitch_api.get_port_ofport_by_id.retrun_value = 2

        mock_update_patch = mock.patch.object(
                self.controller.db_store2,
                'update',
                side_effect=self.controller.db_store2.update
        )
        mock_update = mock_update_patch.start()
        self.addCleanup(mock_update_patch.stop)

        mock_emit_created_patch = mock.patch.object(
                lport, 'emit_local_created')
        mock_emit_created = mock_emit_created_patch.start()
        self.addCleanup(mock_emit_created_patch.stop)

        self.controller.update_migration_flows(lport)
        mock_update.assert_called_with(lport)
        mock_emit_created.assert_called_with()

    @mock.patch.object(db_store2.DbStore2, 'get_one')
    def test__is_physical_chassis(self, get_one):
        # real chassis
        chassis_real = core.Chassis(id='ch1', ip='10.0.0.3')
        self.assertTrue(self.controller._is_physical_chassis(chassis_real))

        self.db_store2 = mock.MagicMock()
        get_one.return_value = core.Chassis(id='ch2', ip='10.0.0.4')
        chassis_ref = model_proxy.create_reference(core.Chassis, 'ch2')
        self.assertTrue(self.controller._is_physical_chassis(chassis_ref))

        get_one.return_value = None
        chassis_bad_ref = model_proxy.create_reference(core.Chassis, 'ch3')
        self.assertFalse(self.controller._is_physical_chassis(chassis_bad_ref))

        chassis_virt = core.Chassis(id=constants.DRAGONFLOW_VIRTUAL_PORT)
        self.assertFalse(self.controller._is_physical_chassis(chassis_virt))

    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store2.DbStore2, 'update')
    def test_update_model_object_created_called(self, update, get_one):
        obj = mock.MagicMock()
        obj.version = 1

        get_one.return_value = None
        self.controller.update_model_object(obj)
        update.assert_called_once_with(obj)
        obj.emit_created.assert_called_once()

    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store2.DbStore2, 'update')
    def test_update_model_object_updated_called(self, update, get_one):
        obj = mock.MagicMock()
        obj.version = 2

        old_obj = mock.MagicMock()
        old_obj.version = 1

        get_one.return_value = old_obj
        self.controller.update_model_object(obj)
        update.assert_called_once_with(obj)
        obj.emit_updated.assert_called_once_with(old_obj)

    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store2.DbStore2, 'update')
    def test_update_model_object_not_called(self, update, get_one):
        obj = mock.MagicMock()
        obj.version = 1
        obj.is_newer_than.return_value = False

        old_obj = mock.MagicMock()
        old_obj.version = 1

        get_one.return_value = old_obj
        self.controller.update_model_object(obj)
        update.assert_not_called()
        obj.emit_updated.assert_not_called()

    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store2.DbStore2, 'delete')
    def test_delete_model_object_called(self, delete, get_one):
        obj = mock.MagicMock()
        obj.emit_deleted = mock.MagicMock()

        get_one.return_value = obj
        self.controller.delete_model_object(obj)
        delete.assert_called_once()
        obj.emit_deleted.assert_called_once()

    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store2.DbStore2, 'delete')
    def test_delete_model_object_not_called(self, delete, get_one):
        get_one.return_value = None
        self.controller.delete_model_object(None)
        delete.assert_not_called()
