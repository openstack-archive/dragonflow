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
from dragonflow.common import utils
from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.db import db_store
from dragonflow.db import db_store2
from dragonflow.db import model_proxy
from dragonflow.db.models import core
from dragonflow.tests.unit import test_app_base


class DfLocalControllerTestCase(test_app_base.DFAppTestBase):

    apps_list = "l2_app.L2App"

    def _get_mock_floatingip(self, lport_id, fip_id):
        floatingip = mock.Mock()
        floatingip.get_lport_id.return_value = lport_id
        floatingip.get_id.return_value = fip_id
        return floatingip

    @mock.patch.object(df_local_controller.DfLocalController,
                       '_update_floatingip')
    @mock.patch.object(utils, 'is_valid_version')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_associate_floatingip')
    @mock.patch.object(db_store.DbStore, 'get_floatingip')
    @mock.patch.object(db_store.DbStore, 'get_local_port')
    def test_floatingip_updated(self, mock_get_lport, mock_get_fip,
                                mock_assoc, mock_is_valid, mock_update):
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        mock_get_lport.return_value = None
        self.assertIsNone(self.controller.update_floatingip(fip))
        mock_get_lport.assert_called_once_with(lport_id)

        mock_get_fip.return_value = None
        fip.get_lport_id.return_value = None
        self.assertIsNone(self.controller.update_floatingip(fip))
        mock_get_fip.assert_called_once_with(fip_id)

        mock_get_lport.return_value = mock.Mock()
        fip.get_lport_id.return_value = lport_id
        self.assertIsNone(self.controller.update_floatingip(fip))
        mock_assoc.assert_called_once_with(fip)

        old_fip = mock.Mock()
        mock_get_fip.return_value = old_fip
        mock_is_valid.return_value = False
        self.assertIsNone(self.controller.update_floatingip(fip))
        mock_is_valid.assert_called_once()

        mock_is_valid.return_value = True
        self.controller.update_floatingip(fip)
        mock_update.assert_called_once_with(old_fip, fip)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_delete_floatingip')
    @mock.patch.object(db_store.DbStore, 'get_floatingip')
    def test_floatingip_deleted(self, mock_get_fip, mock_notify):
        mock_get_fip.return_value = None
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        self.assertIsNone(self.controller.delete_floatingip(fip_id))
        mock_get_fip.return_value = fip
        self.controller.delete_floatingip(fip_id)
        mock_notify.assert_called_once_with(fip)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_associate_floatingip')
    @mock.patch.object(db_store.DbStore, 'update_floatingip')
    def test__associate_floatingip(self, mock_update, mock_notify):
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        self.controller._associate_floatingip(fip)
        mock_update.assert_called_once_with(fip_id, fip)
        mock_notify.assert_called_once_with(fip)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_disassociate_floatingip')
    @mock.patch.object(db_store.DbStore, 'delete_floatingip')
    def test__disassociate_floatingip(self, mock_delete, mock_notify):
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        self.controller._disassociate_floatingip(fip)
        mock_delete.assert_called_once_with(fip_id)
        mock_notify.assert_called_once_with(fip)

    @mock.patch.object(df_local_controller.DfLocalController,
                       '_associate_floatingip')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_disassociate_floatingip')
    def test__update_floatingip(self, mock_disassoc, mock_assoc):
        old_lport_id = 'fake_old_lport_id'
        old_fip_id = 'fake_old_fip_id'
        old_fip = self._get_mock_floatingip(old_lport_id, old_fip_id)
        new_lport_id = 'fake_new_lport_id'
        new_fip_id = 'fake_new_fip_id'
        new_fip = self._get_mock_floatingip(new_lport_id, new_fip_id)
        self.controller._update_floatingip(old_fip, new_fip)
        mock_disassoc.called_once_with(old_fip)
        mock_assoc.called_once_with(new_fip)

    @mock.patch.object(ryu_base_app.RyuDFAdapter, 'notify_ovs_sync_finished')
    def test_ovs_sync_finished(self, mock_notify):
        self.controller.ovs_sync_finished()
        mock_notify.assert_called_once()

    @mock.patch.object(ryu_base_app.RyuDFAdapter, 'notify_ovs_sync_started')
    def test_ovs_sync_started(self, mock_notify):
        self.controller.ovs_sync_started()
        mock_notify.assert_called_once()

    def test_logical_port_updated(self):
        lport = mock.Mock()
        lport.get_chassis.return_value = "lport-fake-chassis"
        lport.get_id.return_value = "lport-fake-id"
        lport.get_lswitch_id.return_value = "lport-fake-lswitch"
        lport.get_remote_vtep.return_value = False
        self.controller.update_lport(lport)
        lport.set_external_value.assert_not_called()

    @mock.patch.object(df_local_controller.DfLocalController,
                       'delete_lport')
    @mock.patch.object(db_store.DbStore, 'get_ports_by_chassis')
    @mock.patch.object(db_store2.DbStore2, 'delete')
    def test_delete_chassis(self, mock_db_store2_delete,
                            mock_get_ports, mock_delete_lport):
        lport_id = 'fake_lport_id'
        chassis = core.Chassis(id='fake_chassis_id')
        lport = mock.Mock()
        lport.get_id.return_value = lport_id
        mock_get_ports.return_value = [lport]

        self.controller.delete_chassis(chassis)
        mock_delete_lport.assert_called_once_with(lport_id)
        mock_db_store2_delete.assert_called_once_with(chassis)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_update_active_port')
    @mock.patch.object(db_store.DbStore, 'update_active_port')
    @mock.patch.object(db_store.DbStore, 'get_local_port')
    @mock.patch.object(db_store.DbStore, 'get_active_port')
    def test_update_activeport(self, mock_get_active, mock_get_local,
                               mock_update, mock_notify):
        active_port = mock.Mock()
        active_port.get_id.return_value = 'fake_id'
        active_port.get_topic.return_value = 'fake_topic'
        active_port.get_detected_lport_id.return_value = 'fake_lport_id'
        mock_get_active.return_value = None
        mock_update.return_value = None

        mock_get_local.return_value = None
        self.assertIsNone(self.controller.update_activeport(active_port))
        mock_notify.assert_not_called()

        lport = mock.Mock()
        mock_get_local.return_value = lport
        self.assertIsNone(self.controller.update_activeport(active_port))
        mock_notify.assert_called_once_with(active_port, None)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_remove_active_port')
    @mock.patch.object(db_store.DbStore, 'delete_active_port')
    @mock.patch.object(db_store.DbStore, 'get_local_port')
    @mock.patch.object(db_store.DbStore, 'get_active_port')
    def test_delete_activeport(self, mock_get_active, mock_get_local,
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
        mock_get_local.return_value = lport
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

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_remove_remote_port')
    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_add_local_port')
    @mock.patch.object(db_store.DbStore, 'set_port')
    def test_update_migration_flows(self, mock_set_port,
                                    mock_notify_add, mock_notify_remove):
        self.controller.nb_api.get_lport_migration.return_value = {}
        self.controller.nb_api.get_lport_migration.return_value = \
            {'migration': 'fake_host'}
        lport = test_app_base.fake_local_port1
        fake_lswitch = test_app_base.fake_logic_switch1

        self.controller.db_store2.update(fake_lswitch)
        self.controller.vswitch_api.get_chassis_ofport.return_value = 3
        self.controller.vswitch_api.get_port_ofport_by_id.retrun_value = 2
        self.controller.db_store.set_port(lport.get_id(), lport, True,
                                          'fake_tenant1')

        self.controller.update_migration_flows(lport)
        mock_set_port.assert_called_with(lport.get_id(), lport, True)
        mock_notify_remove.assert_not_called()
        mock_notify_add.assert_called_with(lport)

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
    @mock.patch.object(db_store2.DbStore2, 'delete')
    def test_delete_model_object_called(self, delete, get_one):
        obj = mock.MagicMock()
        obj.emit_deleted = mock.MagicMock()

        get_one.return_value = obj
        self.controller.delete_model_object(obj)
        self.assertTrue(delete.called)

    @mock.patch.object(db_store2.DbStore2, 'get_one')
    @mock.patch.object(db_store2.DbStore2, 'delete')
    def test_delete_model_object_not_called(self, delete, get_one):
        get_one.return_value = None
        self.controller.delete_model_object(None)
        self.assertFalse(delete.called)
