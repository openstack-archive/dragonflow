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

import time

from dragonflow.ovsdb import vswitch_impl
from dragonflow.tests.fullstack import test_base


class TestChassis(test_base.DFTestBase):

    def setUp(self):
        super(TestChassis, self).setUp()
        self.vswitch_api = vswitch_impl.OvsApi(self.local_ip)
        self.vswitch_api.initialize(self.nb_api)
        self.remote_chassis = {"id": 'test_chassis',
                               "ip": '1.2.3.4',
                               "tunnel_type": self.conf.tunnel_type}
        self.addCleanup(self._cleanUp)

    def test_add_chassis(self):
        self.nb_api.add_chassis(self.remote_chassis.get('id'),
                            ip=self.remote_chassis.get('ip'),
                            tunnel_type=self.remote_chassis.get('tunnel_type'))
        time.sleep(self.conf.monitor_table_poll_time * 2)
        ret = self._get_remote_tunnul_port(
                                self.remote_chassis.get('id'))
        self.assertIsNotNone(ret)
        self.assertEqual(ret.get_remote_ip(),
                         self.remote_chassis.get('ip'))
        self.assertEqual(ret.get_type(),
                         self.remote_chassis.get('tunnel_type'))

        # change the chassis info
        self.nb_api.update_chassis(self.remote_chassis.get('id'),
                            ip='2.3.4.5',
                            tunnel_type=self.remote_chassis.get('tunnel_type'))
        time.sleep(self.conf.monitor_table_poll_time * 2)
        ret = self._get_remote_tunnul_port(
                                self.remote_chassis.get('id'))
        self.assertIsNotNone(ret)
        self.assertEqual(ret.get_remote_ip(), '2.3.4.5')
        self.assertEqual(ret.get_type(),
                         self.remote_chassis.get('tunnel_type'))

        # del chassis
        self.nb_api.delete_chassis(self.remote_chassis.get('id'))
        time.sleep(self.conf.monitor_table_poll_time * 2)
        ret = self._get_remote_tunnul_port(
                                self.remote_chassis.get('id'))
        self.assertIsNone(ret)

    def _get_remote_tunnul_port(self, chassis):
        t_ports = self.vswitch_api.get_tunnel_ports()
        for t_port in t_ports:
            if t_port.get_chassis_id() == self.remote_chassis.get('id'):
                return t_port

    def _cleanUp(self):
        self.nb_api.delete_chassis(self.remote_chassis.get('id'))
