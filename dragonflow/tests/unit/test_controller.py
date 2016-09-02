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
from ryu.base.app_manager import AppManager

from dragonflow.controller import df_local_controller
from dragonflow.controller import dispatcher
from dragonflow.db import api_nb
from dragonflow.db import db_store
from dragonflow.db.drivers import ovsdb_vswitch_impl
from dragonflow.tests import base as tests_base


class TestDfController(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDfController, self).setUp()
        dispatcher.AppDispatcher = mock.Mock()
        db_store.DbStore = mock.Mock()
        cfg.CONF = mock.Mock()
        cfg.CONF.df.local_ip = '192.168.202.10'
        cfg.CONF.df.tunnel_type = 'vxlan'
        self.controller = df_local_controller.DfLocalController('chassis1')

        ovsdb_vswitch_impl.OvsdbSwitchApi = mock.Mock()
        api_nb.NbApi = mock.Mock()
        AppManager.get_instance = mock.Mock()


    def test_register_chassis(self):
        chassis = {"id": 'chassis1',
                   "ip": '192.168.202.10',
                   "tunnel_type": 'vxlan'}
        old_chassis = {"id": 'chassis1',
                       "ip": '192.168.202.110',
                       "tunnel_type": 'nvgre'}
        local_chassis = api_nb.Chassis(chassis)
        old_local_chassis = api_nb.Chassis(old_chassis)

        self.controller.nb_api.get_chassis = mock.Mock(return_value=None)
        self.controller.nb_api.add_chassis = mock.Mock()
        self.controller.register_chassis()
        self.controller.nb_api.add_chassis.assert_called_once_with(
                chassis)

        self.controller.nb_api.get_chassis = mock.Mock(return_value=old_local_chassis)
        self.controller.register_chassis()
        self.controller.nb_api.update_chassis = mock.Mock()
        self.controller.nb_api.update_chassis.assert_called_once_with(
                chassis)

        self.controller.nb_api.add_chassis.reset_mock()
        self.controller.nb_api.update_chassis.reset_mock()
        self.controller.nb_api.get_chassis = local_chassis
        self.controller.register_chassis()
        self.controller.nb_api.add_chassis.assert_not_called()
        self.controller.nb_api.update_chassis.assert_not_called()

    def test_chassis_can_be_added(self):
        local_chassis = {"id": 'chassis1',
                   "ip": '192.168.202.10',
                   "tunnel_type": 'vxlan'}
        diff_tunnel_type = {"id": 'chassis2',
                   "ip": '192.168.202.105',
                   "tunnel_type": 'gre'}
        new_chassis = {"id": 'chassis2',
                   "ip": '192.168.202.205',
                   "tunnel_type": 'vxlan'}
        self.assertFalse(self._remote_chassis_can_be_added(local_chassis))
        self.assertFalse(self._remote_chassis_can_be_added(diff_tunnel_type))
        self.assertTrue(self._remote_chassis_can_be_added(new_chassis))

    @mock.patch(ovsdb_vswitch_impl.OvsdbTunnelPort)
    def test_chassis_updated(self, MockedOvsdbTunnelPort):
        existed_chassis = {"id": 'chassis1',
                   "ip": '192.168.202.205',
                   "tunnel_type": 'vxlan'}
        ip_changed_chassis = {"id": 'chassis2',
                   "ip": '192.168.202.215',
                   "tunnel_type": 'vxlan'}
        new_chassis = {"id": 'chassis3',
                   "ip": '192.168.202.225',
                   "tunnel_type": 'vxlan'}

        t_port1 = MockedOvsdbTunnelPort()
        t_port1.get_chassis_id = 'chassis1'
        t_port1.get_remote_ip = '192.168.202.205'
        t_port1.get_type = 'vxlan'

        t_port2 = MockedOvsdbTunnelPort()
        t_port2.get_chassis_id = 'chassis2'
        t_port2.get_remote_ip = '192.168.202.215'
        t_port2.get_type = 'vxlan'

        t_port3 = MockedOvsdbTunnelPort()
        t_port3.get_chassis_id = 'chassis3'
        t_port3.get_remote_ip = '192.168.202.225'
        t_port3.get_type = 'vxlan'

        t_ports = list(t_port1, t_port2, t_port3)
        self.vswitch_api.get_tunnel_ports = mock.Mock(return_value=t_ports)

        self.chassis_updated(existed_chassis)
        self.vswitch_api.add_tunnel_port.assert_not_called()

        self.chassis_updated(ip_changed_chassis)
        self.vswitch_api.delete_port.assert_called_once_with(t_port2)
        self.vswitch_api.add_tunnel_port.assert_called_once_with(t_port2)

        self.chassis_updated(new_chassis)
        self.vswitch_api.delete_port.assert_not_called()
        self.vswitch_api.add_tunnel_port.assert_called_once_with(t_port3)

