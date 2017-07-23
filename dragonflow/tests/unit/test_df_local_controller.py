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

from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.db import db_store
from dragonflow.db import model_framework
from dragonflow.db.models import core
from dragonflow.db.models import mixins
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_app_base


@model_framework.construct_nb_db_model
class _Model(model_framework.ModelBase, mixins.BasicEvents, mixins.Version):
    table_name = 'some_table'


@model_framework.construct_nb_db_model
class _ModelNoEvents(model_framework.ModelBase, mixins.Version):
    table_name = 'another_table'


class DfLocalControllerTestCase(test_app_base.DFAppTestBase):

    apps_list = ["l2"]

    @mock.patch.object(ryu_base_app.RyuDFAdapter, 'notify_ovs_sync_finished')
    def test_ovs_sync_finished(self, mock_notify):
        self.controller.ovs_sync_finished()
        mock_notify.assert_called_once()

    @mock.patch.object(ryu_base_app.RyuDFAdapter, 'notify_ovs_sync_started')
    def test_ovs_sync_started(self, mock_notify):
        self.controller.ovs_sync_started()
        mock_notify.assert_called_once()

    @mock.patch.object(df_local_controller.DfLocalController,
                       'delete_model_object')
    @mock.patch.object(db_store.DbStore, 'get_all')
    @mock.patch.object(db_store.DbStore, 'delete')
    def test_delete_chassis(self, mock_db_store_delete,
                            mock_get_ports, mock_controller_delete):
        lport_id = 'fake_lport_id'
        chassis = core.Chassis(id='fake_chassis_id')
        lport = mock.Mock()
        lport.id = lport_id
        mock_get_ports.return_value = [lport]

        self.controller.delete(chassis)
        mock_controller_delete.assert_called_once_with(lport)
        mock_db_store_delete.assert_called_once_with(chassis)

    @utils.with_nb_objects(test_app_base.fake_chassis1)
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

        self.assertIn(expected_chassis, self.controller.db_store)
        self.nb_api.update.assert_called_once_with(
            expected_chassis,
            skip_send_event=True,
        )

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'update')
    def test_update_model_object_created_called(self, update, get_one):
        obj = _Model(id='foo', version=1)
        obj.emit_created = mock.Mock()

        get_one.return_value = None
        self.controller.update_model_object(obj)
        update.assert_called_once_with(obj)
        obj.emit_created.assert_called_once()

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'update')
    def test_update_model_object_updated_called(self, update, get_one):
        obj = _Model(id='foo', version=2)
        obj.emit_updated = mock.Mock()

        old_obj = _Model(id='foo', version=1)

        get_one.return_value = old_obj
        self.controller.update_model_object(obj)
        update.assert_called_once_with(obj)
        obj.emit_updated.assert_called_once_with(old_obj)

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'update')
    def test_update_model_object_updated_called_no_events(self, update,
                                                          get_one):
        obj = _ModelNoEvents(id='foo', version=2)
        old_obj = _ModelNoEvents(id='foo', version=1)

        get_one.return_value = old_obj
        self.controller.update_model_object(obj)
        update.assert_called_once_with(obj)

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'update')
    def test_update_model_object_not_called(self, update, get_one):
        obj = _Model(id='foo', version=1)
        obj.emit_updated = mock.Mock()

        old_obj = _Model(id='foo', version=1)

        get_one.return_value = old_obj
        self.controller.update_model_object(obj)
        update.assert_not_called()
        obj.emit_updated.assert_not_called()

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'update')
    def test_update_model_object_not_called_no_events(self, update, get_one):
        obj = _ModelNoEvents(id='foo', version=1)
        old_obj = _ModelNoEvents(id='foo', version=1)
        get_one.return_value = old_obj
        self.controller.update_model_object(obj)
        update.assert_not_called()

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'delete')
    def test_delete_model_object_called(self, delete, get_one):
        obj = _Model(id='foo', version=1)
        obj.emit_deleted = mock.MagicMock()

        get_one.return_value = obj
        self.controller.delete_model_object(obj)
        delete.assert_called_once()
        obj.emit_deleted.assert_called_once()

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'delete')
    def test_delete_model_object_called_no_events(self, delete, get_one):
        obj = _ModelNoEvents(id='foo', version=1)
        get_one.return_value = obj
        self.controller.delete_model_object(obj)
        delete.assert_called_once()

    @mock.patch.object(db_store.DbStore, 'get_one')
    @mock.patch.object(db_store.DbStore, 'delete')
    def test_delete_model_object_not_called(self, delete, get_one):
        get_one.return_value = None
        self.controller.delete_model_object(None)
        delete.assert_not_called()
