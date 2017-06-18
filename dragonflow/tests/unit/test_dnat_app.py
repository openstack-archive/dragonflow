# Copyright (c) 2016 OpenStack Foundation.
# All Rights Reserved.
#
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
from neutron_lib import constants as n_const

from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_app_base


floating_lport = l2.LogicalPort(
    id='floating_lport1',
    topic='topic1',
)

local_lport1 = l2.LogicalPort(
    id='lport1',
    topic='topic1',
    unique_key=1,
    binding=test_app_base.local_binding,
)
local_lport2 = l2.LogicalPort(
    id='lport2',
    topic='topic1',
    unique_key=2,
    binding=test_app_base.local_binding,
)

remote_lport = l2.LogicalPort(
    id='lport3',
    topic='topic1',
    unique_key=3,
    binding=test_app_base.remote_binding,
)

floatingip1 = l3.FloatingIp(
    id='floatingip1',
    topic='tenant1',
    name='no_fip_name',
    version=7,
    status=n_const.FLOATINGIP_STATUS_DOWN,
    floating_ip_address='172.24.4.2',
    floating_lport='floating_lport1',
    lrouter='fake_router_id',
)


class TestDNATApp(test_app_base.DFAppTestBase):
    apps_list = ["dnat"]

    def setUp(self):
        super(TestDNATApp, self).setUp(enable_selective_topo_dist=True)
        self.dnat_app = self.open_flow_app.dispatcher.apps[0]
        self.dnat_app.external_ofport = 99
        self.dnat_app._install_local_floatingip = mock.Mock()
        self.dnat_app._uninstall_local_floatingip = mock.Mock()
        self.dnat_app._install_remote_floatingip = mock.Mock()
        self.dnat_app._uninstall_remote_floatingip = mock.Mock()

    def test_delete_port_with_deleted_floatingip(self):
        self.controller.update(local_lport1)
        self.controller.update(floatingip1)
        self.controller.delete(floatingip1)

        self.dnat_app._remove_local_port(local_lport1)
        self.dnat_app._uninstall_local_floatingip.assert_not_called()
        self.dnat_app._uninstall_remote_floatingip.assert_not_called()

    def test_floatingip_removed_only_once(self):
        self.controller.update(test_app_base.fake_local_port1)
        self.controller.topology.ovs_port_updated(test_app_base.fake_ovs_port1)
        self.controller.update(test_app_base.fake_floatingip1)
        self.controller.delete(test_app_base.fake_floatingip1)
        self.controller.delete(test_app_base.fake_local_port1)
        with mock.patch.object(self.controller, 'delete') as mock_func:
            self.controller.topology.ovs_port_deleted(
                test_app_base.fake_ovs_port1)
            mock_func.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1, floating_lport)
    def test_install_remote_floatingip_called_on_create(self):
        fip = l3.FloatingIp(
            id='fake_id',
            lport=local_lport1,
            floating_lport=floating_lport,
        )

        fip.emit_created()
        self._install_local_floatingip.assert_called_once_with(
            fip,
            update_status=True,
        )

    @utils.add_objs_to_db_store(remote_lport, floating_lport)
    def test_install_local_floatingip_called_on_create(self):
        fip = l3.FloatingIp(
            id='fake_id',
            lport=remote_lport,
            floating_lport=floating_lport,
        )

        fip.emit_created()
        self._install_remote_floatingip.assert_called_once_with(fip)

    def test_associate_floatingip_not_called_on_create(self):
        fip = l3.FloatingIp(id='fake_id')

        with self._with_mock_install_uninstall() as (a, _):
            fip.emit_created()
            a.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1)
    def test_disassociate_floatingip_called_on_delete(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._with_mock_install_uninstall() as (_, d):
            fip.emit_deleted()
            d.assert_called_once_with(fip)

    def test_disassociate_floatingip_not_called_on_delete(self):
        fip = l3.FloatingIp(id='fake_id')

        with self._with_mock_install_uninstall() as (_, d):
            fip.emit_deleted()
            d.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1, local_lport2)
    def test_reassociate_on_lport_change(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport2)
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._with_mock_install_uninstall() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_called_once_with(fip)
            d.assert_called_once_with(old_fip)

    @utils.add_objs_to_db_store(local_lport1, remote_lport)
    def test_reassociate_on_lport_change_non_local(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        fip = l3.FloatingIp(id='fake_id', lport=remote_lport)

        with self._with_mock_install_uninstall() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_not_called()
            d.assert_called_once_with(old_fip)

    @utils.add_objs_to_db_store(local_lport1)
    def test_no_reassociate_on_update(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._with_mock_install_uninstall() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_not_called()
            d.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1)
    def test_associate_on_update(self):
        old_fip = l3.FloatingIp(id='fake_id')
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._with_mock_install_uninstall() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_called_once_with(fip)
            d.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1)
    def test_disassociate_on_update(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        fip = l3.FloatingIp(id='fake_id')

        with self._with_mock_install_uninstall() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_not_called()
            d.assert_called_once_with(old_fip)

    @utils.add_objs_to_db_store(local_lport1)
    def test_remove_local_lport(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        local_lport1.emit_local_deleted()
        d.assert_called_once_with(fip)
