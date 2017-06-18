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

from dragonflow.controller import port_locator
from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_app_base


floating_lport = l2.LogicalPort(
    id='floating_lport1',
    topic='topic1',
    unique_key=1,
    version=1,
)

local_lport1 = l2.LogicalPort(
    id='lport1',
    topic='topic1',
    unique_key=2,
    version=1,
    binding=test_app_base.local_binding,
)
local_lport2 = l2.LogicalPort(
    id='lport2',
    topic='topic1',
    unique_key=3,
    version=1,
    binding=test_app_base.local_binding,
)

remote_lport = l2.LogicalPort(
    id='lport3',
    topic='topic1',
    unique_key=4,
    version=1,
    binding=test_app_base.remote_binding,
)

floatingip1 = l3.FloatingIp(
    id='floatingip1',
    topic='tenant1',
    name='no_fip_name',
    version=7,
    floating_ip_address='172.24.4.2',
    floating_lport='floating_lport1',
    lrouter='fake_router_id',
)


class TestDNATApp(test_app_base.DFAppTestBase):
    apps_list = ["dnat"]

    def setUp(self):
        super(TestDNATApp, self).setUp(enable_selective_topo_dist=True)
        self.dnat_app = self.open_flow_app.dispatcher.apps['dnat']
        self.dnat_app.external_ofport = 99
        self._mock_dnat_method('_install_local_floatingip')
        self._mock_dnat_method('_uninstall_local_floatingip')
        self._mock_dnat_method('_install_remote_floatingip')
        self._mock_dnat_method('_uninstall_remote_floatingip')
        port_locator.reset()

    def _mock_dnat_method(self, name):
        orig = getattr(self.dnat_app, name)
        m = mock.Mock()
        setattr(self.dnat_app, name, m)
        m.orig = orig

    def test_delete_port_with_deleted_floatingip(self):
        self.controller.update(local_lport1)
        self.controller.update(floatingip1)
        self.controller.delete(floatingip1)

        local_lport1.emit_unbind_local()
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
    def test_install_local_floatingip_called_on_create(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=4,
            lport=local_lport1,
            floating_lport=floating_lport,
        )

        fip.emit_created()
        self.dnat_app._install_local_floatingip.assert_called_once_with(fip)

    @utils.add_objs_to_db_store(remote_lport, floating_lport)
    def test_install_remote_floatingip_called_on_create(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=4,
            lport=remote_lport,
            floating_lport=floating_lport,
        )

        fip.emit_created()
        self.dnat_app._install_remote_floatingip.assert_called_once_with(fip)

    def test_install_floatingip_not_called_on_create(self):
        l3.FloatingIp(id='fake_id').emit_created()
        self.dnat_app._install_local_floatingip.assert_not_called()
        self.dnat_app._install_remote_floatingip.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1, floating_lport)
    def test_uninstall_local_floatingip_called_on_delete(self):
        fip = l3.FloatingIp(
            id='fake_id',
            lport=local_lport1,
            floating_lport=floating_lport,
        )
        fip.emit_deleted()
        self.dnat_app._uninstall_local_floatingip.assert_called_once_with(fip)

    @utils.add_objs_to_db_store(remote_lport, floating_lport)
    def test_uninstall_remote_floatingip_called_on_delete(self):
        fip = l3.FloatingIp(
            id='fake_id',
            lport=remote_lport,
            floating_lport=floating_lport,
        )
        fip.emit_deleted()
        self.dnat_app._uninstall_remote_floatingip.assert_called_once_with(fip)

    @utils.add_objs_to_db_store(local_lport1)
    def test_floating_port_deleted_before_fip_delete(self):
        fip = l3.FloatingIp(
            id='fake_id',
            lport=local_lport1,
            floating_lport=floating_lport,
        )
        fip.emit_deleted()
        self.dnat_app._uninstall_local_floatingip.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1, local_lport2)
    def test_reassociate_on_lport_change(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport2)
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        fip.emit_updated(old_fip)
        self.dnat_app._install_local_floatingip.assert_called_once_with(fip)
        self.dnat_app._uninstall_local_floatingip.assert_called_once_with(
            old_fip)

    @utils.add_objs_to_db_store(local_lport1, remote_lport, floating_lport)
    def test_reassociate_on_lport_change_non_local(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        fip = l3.FloatingIp(id='fake_id', lport=remote_lport)

        fip.emit_updated(old_fip)
        self.dnat_app._uninstall_local_floatingip.assert_called_once_with(
            old_fip)
        self.dnat_app._install_remote_floatingip.assert_called_once_with(fip)

    @utils.add_objs_to_db_store(local_lport1)
    def test_no_reassociate_on_update(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        fip.emit_updated(old_fip)
        self.dnat_app._install_local_floatingip.assert_not_called()
        self.dnat_app._uninstall_local_floatingip.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1)
    def test_install_on_update(self):
        old_fip = l3.FloatingIp(id='fake_id')
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        fip.emit_updated(old_fip)
        self.dnat_app._install_local_floatingip.assert_called_once_with(fip)

    @utils.add_objs_to_db_store(local_lport1)
    def test_uninstall_on_update(self):
        old_fip = l3.FloatingIp(
            id='fake_id',
            topic='topic',
            version=4,
            lport=local_lport1,
        )
        fip = l3.FloatingIp(id='fake_id')
        fip.emit_updated(old_fip)
        self.dnat_app._uninstall_local_floatingip.assert_called_once_with(
            old_fip)

    def test_add_local_lport(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=1,
            lport=local_lport1,
        )
        self.dnat_app.db_store.update(fip)
        local_lport1.emit_bind_local()
        self.dnat_app._install_local_floatingip.assert_called_once_with(fip)

    def test_remove_local_lport(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=1,
            lport=local_lport1,
        )
        self.dnat_app.db_store.update(fip)
        local_lport1.emit_unbind_local()
        self.dnat_app._uninstall_local_floatingip.assert_called_once_with(fip)

    def test_add_remote_lport(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=1,
            lport=remote_lport,
        )
        self.dnat_app.db_store.update(fip)
        remote_lport.emit_bind_remote()
        self.dnat_app._install_remote_floatingip.assert_called_once_with(fip)

    def test_remove_remote_lport(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=1,
            lport=remote_lport,
        )
        self.dnat_app.db_store.update(fip)
        remote_lport.emit_unbind_remote()
        self.dnat_app._uninstall_remote_floatingip.assert_called_once_with(fip)

    @utils.add_objs_to_db_store(local_lport1, floating_lport)
    def test_local_floating_lport_deleted(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=1,
            lport=local_lport1,
            floating_lport=floating_lport,
        )
        self.dnat_app.db_store.update(fip)

        m = mock.Mock()

        def cb(lport):
            if lport.id == floating_lport.id:
                m()

        l2.LogicalPort.register_unbind_local(cb)
        floating_lport.emit_bind_local()

        self.controller.delete(floating_lport)
        m.assert_called_once_with()
        self.dnat_app._uninstall_local_floatingip.assert_called_once_with(
            fip, emit_unbind=False)

    @utils.add_objs_to_db_store(remote_lport, floating_lport)
    def test_remote_floating_lport_deleted(self):
        fip = l3.FloatingIp(
            id='fake_id',
            topic='topic1',
            version=1,
            lport=remote_lport,
            floating_lport=floating_lport,
        )
        self.dnat_app.db_store.update(fip)

        m = mock.Mock()

        def cb(lport):
            if lport.id == floating_lport.id:
                m()

        l2.LogicalPort.register_unbind_remote(cb)
        floating_lport.emit_bind_remote()

        self.controller.delete(floating_lport)
        m.assert_called_once_with()
        self.dnat_app._uninstall_remote_floatingip.assert_called_once_with(
            fip, emit_unbind=False)
