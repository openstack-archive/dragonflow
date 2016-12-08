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

from dragonflow.controller import df_local_controller
from dragonflow.controller import ryu_base_app
from dragonflow.db import db_store
from dragonflow.tests.unit import test_app_base


class DfLocalControllerTestCase(test_app_base.DFAppTestBase):

    apps_list = "l2_ml2_app.L2App"

    def _get_mock_chassis(self, chassis_ids):
        all_chassis = []
        for chassis_id in chassis_ids:
            mock_chassis = mock.Mock()
            mock_chassis.get_id.return_value = chassis_id
            all_chassis.append(mock_chassis)
        return all_chassis

    def _get_mock_ports(self, chassis_ids):
        ports = []
        for chassis_id in chassis_ids:
            mock_port = mock.Mock()
            mock_port.get_chassis_id.return_value = chassis_id
            ports.append(mock_port)
        return ports

    def test_chassis_deleted(self):
        ids = ['foo', 'bar']
        mock_ports = self._get_mock_ports(ids)
        self.controller.vswitch_api.get_tunnel_ports.return_value = mock_ports
        self.controller.chassis_deleted(ids[0])
        self.controller.vswitch_api.get_tunnel_ports.assert_called_once_with()
        self.controller.vswitch_api.delete_port.assert_called_once_with(
            mock_ports[0])

    def test_chassis_created_if_self_installed(self):
        mock_ports = self._get_mock_ports(['fake_chassis_id'])
        ids = [self.controller.chassis_name]
        mock_chassis = self._get_mock_chassis(ids)[0]
        self.controller.chassis_updated(mock_chassis)
        self.assertFalse(mock_ports[0].get_chassis_id.called)
        self.assertFalse(self.controller.vswitch_api.add_tunnel_port.called)

    def test_chassis_created_if_remote_installed(self):
        ids = ['fake_chassis_id']
        mock_ports = self._get_mock_ports(ids)
        self.controller.vswitch_api.get_tunnel_ports.return_value = mock_ports
        mock_chassis = self._get_mock_chassis(ids)[0]
        self.controller.chassis_updated(mock_chassis)
        mock_ports[0].get_chassis_id.assert_called_once_with()
        self.assertFalse(self.controller.vswitch_api.add_tunnel_port.called)

    def test_chassis_created(self):
        ids = ['fake_chassis_id']
        mock_chassis = mock.Mock()
        self.controller.vswitch_api.get_tunnel_ports.return_value = (
            self._get_mock_ports(ids))
        self.controller.chassis_updated(mock_chassis)
        self.controller.vswitch_api.add_tunnel_port.assert_called_once_with(
            mock_chassis)

    @mock.patch.object(df_local_controller.DfLocalController,
                       'chassis_updated')
    def test_create_tunnels(self, mock_create):
        shared = mock.Mock()
        port_ids = [shared, 'to_be_deleted']
        chassis_ids = [shared, self.controller.chassis_name, 'else']
        t_ports = self._get_mock_ports(port_ids)
        self.controller.vswitch_api.get_tunnel_ports.return_value = t_ports
        chassis = self._get_mock_chassis(chassis_ids)
        self.controller.nb_api.get_all_chassis.return_value = chassis
        self.controller.create_tunnels()
        self.nb_api.get_all_chassis.assert_called_once()
        self.controller.chassis_updated.assert_called_once_with(chassis[2])
        self.controller.vswitch_api.delete_port.assert_called_once_with(
            t_ports[1])

    def _get_mock_secgroup(self, secgroup_id, rules):
        secgroup = mock.Mock()
        secgroup.get_rules.return_value = rules
        secgroup.get_id.return_value = secgroup_id
        return secgroup

    @mock.patch.object(df_local_controller.DfLocalController,
                       '_add_new_security_group_rule')
    def test_add_new_security_group(self, mock_add):
        rules = ['new_rule']
        secgroup_id = 'fake id'
        mock_secgroup = self._get_mock_secgroup(secgroup_id, rules)
        self.controller._add_new_security_group(mock_secgroup)
        mock_add.assert_called_once_with(mock_secgroup, rules[0])
        sec_group = self.controller.db_store.get_secgroup(secgroup_id)
        self.assertIn(rules[0], sec_group.get_rules())

    @mock.patch.object(db_store.DbStore, 'delete_secgroup')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_delete_security_group_rule')
    def test_delete_old_security_group(self, mock_delete, mock_db_delete):
        rules = ['old_rule']
        secgroup_id = 'fake_id'
        mock_secgroup = self._get_mock_secgroup(secgroup_id, rules)
        self.controller._delete_old_security_group(mock_secgroup)
        mock_delete.assert_called_once_with(mock_secgroup, rules[0])
        mock_db_delete.assert_called_once_with(secgroup_id)

    @mock.patch.object(df_local_controller.DfLocalController,
                       '_delete_security_group_rule')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_add_new_security_group_rule')
    def test_update_security_group_rules(self, mock_add, mock_delete):
        shared_rule = 'to_be_removed'
        secgroup_id = 'fake_id'
        old_rules = [shared_rule, 'old_rule']
        new_rules = [shared_rule, 'new_rule']
        new_secgroup = self._get_mock_secgroup('new_%s' % secgroup_id,
                                               new_rules)
        old_secgroup = self._get_mock_secgroup('old_%s' % secgroup_id,
                                               old_rules)
        self.controller._update_security_group_rules(old_secgroup,
                                                     new_secgroup)
        mock_add.assert_called_once_with(new_secgroup, new_rules[1])

        self.assertNotIn(shared_rule, old_rules)
        mock_delete.assert_called_once_with(old_secgroup, 'old_rule')

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_add_security_group_rule')
    def test_add_new_security_group_rule(self, mock_app_notify):
        secgroup = mock.Mock()
        secgroup_rule = mock.Mock()
        self.controller._add_new_security_group_rule(secgroup, secgroup_rule)
        mock_app_notify.assert_called_once_with(secgroup, secgroup_rule)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_remove_security_group_rule')
    def test_delete_security_group_rule(self, mock_app_notify):
        secgroup = mock.Mock()
        secgroup_rule = mock.Mock()
        self.controller._delete_security_group_rule(secgroup, secgroup_rule)
        mock_app_notify.assert_called_once_with(secgroup, secgroup_rule)

    def _get_mock_floatingip(self, lport_id, fip_id):
        floatingip = mock.Mock()
        floatingip.get_lport_id.return_value = lport_id
        floatingip.get_id.return_value = fip_id
        return floatingip

    @mock.patch.object(df_local_controller.DfLocalController,
                       '_update_floatingip')
    @mock.patch.object(df_local_controller.DfLocalController,
                       '_is_valid_version')
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
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_get_lport.assert_called_once_with(lport_id)

        mock_get_fip.return_value = None
        fip.get_lport_id.return_value = None
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_get_fip.assert_called_once_with(fip_id)

        mock_get_lport.return_value = mock.Mock()
        fip.get_lport_id.return_value = lport_id
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_assoc.assert_called_once_with(fip)

        old_fip = mock.Mock()
        mock_get_fip.return_value = old_fip
        mock_is_valid.return_value = False
        self.assertIsNone(self.controller.floatingip_updated(fip))
        mock_is_valid.assert_called_once()

        mock_is_valid.return_value = True
        self.controller.floatingip_updated(fip)
        mock_update.assert_called_once_with(old_fip, fip)

    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_delete_floatingip')
    @mock.patch.object(db_store.DbStore, 'get_floatingip')
    def test_floatingip_deleted(self, mock_get_fip, mock_notify):
        mock_get_fip.return_value = None
        lport_id = 'fake_lport_id'
        fip_id = 'fake_fip_id'
        fip = self._get_mock_floatingip(lport_id, fip_id)
        self.assertIsNone(self.controller.floatingip_deleted(fip_id))
        mock_get_fip.return_value = fip
        self.controller.floatingip_deleted(fip_id)
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

    @mock.patch.object(db_store.DbStore, 'get_lswitch')
    @mock.patch.object(db_store.DbStore, 'delete_lswitch')
    @mock.patch.object(ryu_base_app.RyuDFAdapter,
                       'notify_delete_lswitch')
    def test_logical_switch_deleted(self, mock_notify_remove,
                                    mock_del_lswitch, mock_get_lswitch):
        lswitch_id = 'theLswitchId'
        lswitch = 'theLswitch'

        mock_get_lswitch.return_value = None
        self.controller.delete_lswitch(lswitch_id)
        self.assertFalse(mock_notify_remove.called)

        mock_notify_remove.mock_reset()
        mock_get_lswitch.return_value = lswitch
        self.controller.delete_lswitch(lswitch_id)
        mock_get_lswitch.assert_called_with(lswitch_id)
        mock_notify_remove.assert_called_with(lswitch)
        mock_del_lswitch.assert_called_with(lswitch_id)

    def test_logical_port_updated(self):
        lport = mock.Mock()
        lport.get_chassis.return_value = "lport-fake-chassis"
        lport.get_id.return_value = "lport-fake-id"
        lport.get_lswitch_id.return_value = "lport-fake-lswitch"
        lport.get_remote_vtep.return_value = False
        self.controller.logical_port_updated(lport)
        lport.set_external_value.assert_not_called()
