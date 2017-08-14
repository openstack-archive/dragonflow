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
import contextlib

import mock

from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.db.models import ovs
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_app_base

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


class TestDNATApp(test_app_base.DFAppTestBase):
    apps_list = ["dnat"]

    def setUp(self):
        super(TestDNATApp, self).setUp(enable_selective_topo_dist=True)
        self.dnat_app = self.open_flow_app.dispatcher.apps['dnat']
        self.dnat_app.external_ofport = 99

    def test_external_bridge_online(self):
        self.dnat_app.local_floatingips[
            test_app_base.fake_floatingip1.id] = (
                test_app_base.fake_floatingip1)

        with mock.patch.object(self.dnat_app,
                               '_install_dnat_egress_rules') as mock_func:

            self.controller.update(
                ovs.OvsPort(
                    id='fake_ovs_port',
                    name=self.dnat_app.external_network_bridge,
                ),
            )
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Other device update will not trigger update flow
            self.controller.update(
                ovs.OvsPort(
                    id='unrelated-device',
                    name='no-bridge',
                    mac_in_use='aa:bb:cc:dd:ee:ff',
                )
            )
            mock_func.assert_not_called()
            mock_func.reset_mock()

            # Device with mac will trigger update flow
            self.controller.update(
                ovs.OvsPort(
                    id='fake_ovs_port',
                    name=self.dnat_app.external_network_bridge,
                    mac_in_use='aa:bb:cc:dd:ee:ff',
                ),
            )
            mock_func.assert_called_once_with(test_app_base.fake_floatingip1,
                                              "aa:bb:cc:dd:ee:ff")
            mock_func.reset_mock()

            # Duplicated updated will not trigger update flow
            self.controller.update(
                ovs.OvsPort(
                    id='fake_ovs_port',
                    name=self.dnat_app.external_network_bridge,
                    mac_in_use='aa:bb:cc:dd:ee:ff',
                    peer='foo',
                ),
            )
            mock_func.assert_not_called()

    def test_delete_port_with_deleted_floatingip(self):
        self.controller.update(test_app_base.fake_local_port1)
        self.controller.update(test_app_base.fake_floatingip1)
        self.controller.delete(test_app_base.fake_floatingip1)

        self.assertFalse(self.dnat_app.local_floatingips)

        with mock.patch.object(
            self.dnat_app,
            '_delete_floatingip',
        ) as mock_func:
            self.dnat_app._remove_local_port(test_app_base.fake_local_port1)
            mock_func.assert_not_called()

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

    @contextlib.contextmanager
    def _mock_assoc_disassoc(self):
        with mock.patch.object(self.dnat_app, '_associate_floatingip') as a:
            with mock.patch.object(
                self.dnat_app, '_disassociate_floatingip'
            ) as d:
                yield a, d

    @utils.add_objs_to_db_store(local_lport1)
    def test_associate_floatingip_called_on_create(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._mock_assoc_disassoc() as (a, _):
            fip.emit_created()
            a.assert_called_once_with(fip)

    def test_associate_floatingip_not_called_on_create(self):
        fip = l3.FloatingIp(id='fake_id')

        with self._mock_assoc_disassoc() as (a, _):
            fip.emit_created()
            a.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1)
    def test_disassociate_floatingip_called_on_delete(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._mock_assoc_disassoc() as (_, d):
            fip.emit_deleted()
            d.assert_called_once_with(fip)

    def test_disassociate_floatingip_not_called_on_delete(self):
        fip = l3.FloatingIp(id='fake_id')

        with self._mock_assoc_disassoc() as (_, d):
            fip.emit_deleted()
            d.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1, local_lport2)
    def test_reassociate_on_lport_change(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport2)
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._mock_assoc_disassoc() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_called_once_with(fip)
            d.assert_called_once_with(old_fip)

    @utils.add_objs_to_db_store(local_lport1, remote_lport)
    def test_reassociate_on_lport_change_non_local(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        fip = l3.FloatingIp(id='fake_id', lport=remote_lport)

        with self._mock_assoc_disassoc() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_not_called()
            d.assert_called_once_with(old_fip)

    @utils.add_objs_to_db_store(local_lport1)
    def test_no_reassociate_on_update(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._mock_assoc_disassoc() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_not_called()
            d.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1)
    def test_associate_on_update(self):
        old_fip = l3.FloatingIp(id='fake_id')
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        with self._mock_assoc_disassoc() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_called_once_with(fip)
            d.assert_not_called()

    @utils.add_objs_to_db_store(local_lport1)
    def test_disassociate_on_update(self):
        old_fip = l3.FloatingIp(id='fake_id', lport=local_lport1)
        fip = l3.FloatingIp(id='fake_id')

        with self._mock_assoc_disassoc() as (a, d):
            fip.emit_updated(old_fip)
            a.assert_not_called()
            d.assert_called_once_with(old_fip)

    @utils.add_objs_to_db_store(local_lport1)
    def test_remove_local_lport(self):
        fip = l3.FloatingIp(id='fake_id', lport=local_lport1)

        self.dnat_app.local_floatingips[fip.id] = fip
        with self._mock_assoc_disassoc() as (_, d):
            local_lport1.emit_unbind_local()
            d.assert_called_once_with(fip)
