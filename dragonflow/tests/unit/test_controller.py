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
from oslo_config import cfg

from dragonflow.controller import df_local_controller
from dragonflow.controller import topology
import dragonflow.db.db_models as models
from dragonflow.tests import base
from dragonflow.tests.unit import test_app_base


class TestController(base.BaseTestCase):
    apps_list = ""

    def setUp(self):
        cfg.CONF.set_override('apps_list', self.apps_list, group='df')
        super(TestController, self).setUp()
        mock.patch('ryu.base.app_manager.AppManager.get_instance').start()
        self.controller = df_local_controller.DfLocalController('fake_host')
        self.nb_api = self.controller.nb_api = mock.MagicMock()
        self.vswitch_api = self.controller.vswitch_api = mock.MagicMock()
        self.controller.topology = topology.Topology(self.controller, True)

        # Add basic network topology
        self.controller.logical_switch_updated(
            test_app_base.fake_logic_switch1)
        self.controller.logical_switch_updated(
            test_app_base.fake_external_switch1)
        self.controller.router_updated(test_app_base.fake_logic_router1)

    def test_floatingip_removedo_only_once(self):
        value1 = mock.Mock(name='ovs_port')
        value1.get_id.return_value = 'ovs_port1'
        value1.get_ofport.return_value = 1
        value1.get_name.return_value = ''
        value1.get_admin_state.return_value = 'True'
        value1.get_type.return_value = 'vm'
        value1.get_iface_id.return_value = 'fake_port1'
        value1.get_peer.return_value = ''
        value1.get_attached_mac.return_value = ''
        value1.get_remote_ip.return_value = ''
        value1.get_tunnel_type.return_value = ''

        ovs_port1 = models.OvsPort(value1)

        self.controller.logical_port_created(test_app_base.fake_local_port1)
        self.controller.topology.ovs_port_updated(ovs_port1)
        self.controller.floatingip_updated(test_app_base.fake_floatingip1)
        self.controller.floatingip_deleted(
            test_app_base.fake_floatingip1.get_id())
        self.controller.logical_port_deleted(
            test_app_base.fake_local_port1.get_id())
        with mock.patch.object(
            self.controller,
            'floatingip_deleted'
        ) as mock_func:
            self.controller.topology.ovs_port_deleted(ovs_port1.get_id())
            mock_func.assert_not_called()
