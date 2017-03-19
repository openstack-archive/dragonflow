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

from dragonflow.common import utils
from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.db import db_store
from dragonflow.db import db_store2
from dragonflow.db.models import core
from dragonflow.db.models import l2
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
    @mock.patch.object(db_store2.DbStore2, 'get_one')
    def test_floatingip_updated(self, mock_get_one, mock_get_fip,
                                mock_assoc, mock_is_valid, mock_update):
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        mock_get_one.return_value = None
        self.assertIsNone(self.controller.update_floatingip(fip))
        mock_get_one.assert_called_once_with(l2.LogicalPort(id=lport_id))

        mock_get_fip.return_value = None
        fip.get_lport_id.return_value = None
        self.assertIsNone(self.controller.update_floatingip(fip))
        mock_get_fip.assert_called_once_with(fip_id)

        mock_get_one.return_value = mock.Mock()
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

    def _get_mock_publisher(self, uri, publisher_id):
        publisher = mock.Mock()
        publisher.get_uri.return_value = uri
        publisher.get_id.return_value = publisher_id
        return publisher

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
