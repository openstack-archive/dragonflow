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
        cfg.CONF.set_override('local_ip',
                              '192.168.202.10',
                              'df')
        cfg.CONF.set_override('tunnel_type',
                              'vxlan',
                              'df')
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

        self.controller.nb_api.get_chassis = mock.Mock(
                                             return_value=old_local_chassis)
        self.controller.nb_api.update_chassis = mock.Mock()
        self.controller.register_chassis()
        self.controller.nb_api.update_chassis.assert_called_with(
                chassis)

        self.controller.nb_api.add_chassis.reset_mock()
        self.controller.nb_api.update_chassis.reset_mock()
        self.controller.nb_api.get_chassis = mock.Mock(
                                             return_value=local_chassis)
        self.controller.register_chassis()
        self.controller.nb_api.add_chassis.assert_not_called()
        self.controller.nb_api.update_chassis.assert_not_called()

    def test_chassis_can_be_added(self):
        _local_chassis = {"id": 'chassis1',
                   "ip": '192.168.202.10',
                   "tunnel_type": 'vxlan'}
        _diff_type_chassis = {"id": 'chassis2',
                   "ip": '192.168.202.105',
                   "tunnel_type": 'gre'}
        _new_chassis = {"id": 'chassis2',
                   "ip": '192.168.202.205',
                   "tunnel_type": 'vxlan'}
        local_chassis = api_nb.Chassis(_local_chassis)
        diff_tunnel_type = api_nb.Chassis(_diff_type_chassis)
        new_chassis = api_nb.Chassis(_new_chassis)
        self.assertFalse(self.controller.
                              _remote_chassis_can_be_added(local_chassis))
        self.assertFalse(self.controller.
                              _remote_chassis_can_be_added(diff_tunnel_type))
        self.assertTrue(self.controller._remote_chassis_can_be_added(new_chassis))

    @mock.patch('dragonflow.db.drivers.ovsdb_vswitch_impl.OvsdbTunnelPort')
    def test_chassis_updated(self, MockedOvsdbTunnelPort):
        _existed_chassis = {"id": 'chassis1',
                   "ip": '192.168.202.205',
                   "tunnel_type": 'vxlan'}
        _ip_changed_chassis = {"id": 'chassis2',
                   "ip": '192.168.202.215',
                   "tunnel_type": 'vxlan'}
        _new_chassis = {"id": 'chassis3',
                   "ip": '192.168.202.225',
                   "tunnel_type": 'vxlan'}
        existed_chassis = api_nb.Chassis(_existed_chassis)
        new_chassis = api_nb.Chassis(_new_chassis)
        ip_changed_chassis = api_nb.Chassis(_ip_changed_chassis)

        MockedOvsdbTunnelPort.side_effect = [mock.Mock(), mock.Mock()]


        t_port1 = MockedOvsdbTunnelPort()
        t_port1.get_chassis_id = mock.Mock(return_value='chassis1')
        t_port1.get_remote_ip = mock.Mock(return_value='192.168.202.205')
        t_port1.get_type = mock.Mock(return_value='vxlan')

        t_port2 = MockedOvsdbTunnelPort()
        t_port2.get_chassis_id = mock.Mock(return_value='chassis2')
        t_port2.get_remote_ip = mock.Mock(return_value='192.168.202.216')
        t_port2.get_type = mock.Mock(return_value='vxlan')

        t_ports = list([t_port1, t_port2])
        self.controller.vswitch_api.get_tunnel_ports = mock.Mock(
                                                       return_value=t_ports)

        self.controller.chassis_updated(existed_chassis)
        self.controller.vswitch_api.add_tunnel_port.assert_not_called()

        self.controller.chassis_updated(new_chassis)
        self.controller.vswitch_api.delete_port.assert_not_called()
        self.controller.vswitch_api.add_tunnel_port.assert_called_once_with(
                                                   new_chassis)

        self.controller.chassis_updated(ip_changed_chassis)
        self.controller.vswitch_api.delete_port.assert_called_once_with(t_port2)
        self.controller.vswitch_api.add_tunnel_port.assert_called_with(
                                                   ip_changed_chassis)

    @mock.patch('dragonflow.db.drivers.ovsdb_vswitch_impl.OvsdbTunnelPort')
    def test_create_tunnels(self, MockedOvsdbTunnelPort):
        MockedOvsdbTunnelPort.side_effect = [mock.Mock(),
                                             mock.Mock(),
                                             mock.Mock()]
        t_port_existed = MockedOvsdbTunnelPort()
        t_port_existed.get_chassis_id = mock.Mock(return_value='chassis1')
        t_port_existed.get_remote_ip = mock.Mock(
                                            return_value='192.168.202.205')
        t_port_existed.get_type = mock.Mock(return_value='vxlan')

        t_port_deleted = MockedOvsdbTunnelPort()
        t_port_deleted.get_chassis_id = mock.Mock(return_value='chassis2')
        t_port_deleted.get_remote_ip = mock.Mock(
                                            return_value='192.168.202.215')
        t_port_deleted.get_type = mock.Mock(return_value='vxlan')

        t_port_updated = MockedOvsdbTunnelPort()
        t_port_updated.get_chassis_id = mock.Mock(return_value='chassis3')
        t_port_updated.get_remote_ip = mock.Mock(
                                            return_value='192.168.202.225')
        t_port_updated.get_type = mock.Mock(return_value='vxlan')

        t_ports = list([t_port_existed, t_port_deleted, t_port_updated])
        self.controller.vswitch_api = mock.Mock()
        self.controller.vswitch_api.get_tunnel_ports = mock.Mock(
                                            return_value=t_ports)

        _existed_chassis = {u"id": 'chassis1',
                            u"ip": '192.168.202.205',
                            u"tunnel_type": 'vxlan'}
        _new_chassis = {u"id": 'chassis4',
                        u"ip": '192.168.202.235',
                        u"tunnel_type": 'vxlan'}
        _ip_changed_chassis = {u"id": 'chassis3',
                               u"ip": '192.168.202.224',
                               u"tunnel_type": 'vxlan'}
        existed_chassis = api_nb.Chassis(_existed_chassis)
        new_chassis = api_nb.Chassis(_new_chassis)
        ip_changed_chassis = api_nb.Chassis(_ip_changed_chassis)

        self.controller.nb_api.get_all_chassis = mock.Mock(
             return_value=[existed_chassis, new_chassis, ip_changed_chassis])

        self.controller.vswitch_api.delete_port = mock.Mock()
        self.controller.vswitch_api.add_tunnel_port = mock.Mock()
        self.controller.create_tunnels()
        self.controller.vswitch_api.delete_port.assert_has_calls(
                     [mock.call(t_port_updated), mock.call(t_port_deleted)],
                     any_order=True)
        self.controller.vswitch_api.add_tunnel_port.assert_has_calls(
                     [mock.call(new_chassis), mock.call(ip_changed_chassis)],
                     any_order=True)
