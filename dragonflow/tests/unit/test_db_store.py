# Copyright (c) 2015 OpenStack Foundation.
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

from dragonflow.db import db_store
from dragonflow.tests import base as tests_base


class TestDbStore(tests_base.BaseTestCase):
    def setUp(self):
        tests_base.BaseTestCase.setUp(self)
        self.db_store = db_store.DbStore()

    def test_lswitch(self):
        self.db_store.set_lswitch('id1', 'value1', 'topic1')
        self.db_store.set_lswitch('id2', 'value2', 'topic2')
        self.db_store.set_lswitch('id3', 'value3', 'topic2')
        self.assertEqual('value1', self.db_store.get_lswitch('id1'))
        self.assertEqual('value2', self.db_store.get_lswitch('id2'))
        self.assertEqual(
            'value1',
            self.db_store.get_lswitch('id1', 'topic1'),
        )
        lswitchs = self.db_store.get_lswitchs()
        lswitchs_topic2 = self.db_store.get_lswitchs('topic2')
        self.assertEqual({'value1', 'value2', 'value3'}, set(lswitchs))
        self.assertIn('value2', lswitchs_topic2)
        self.assertIn('value3', lswitchs_topic2)
        self.db_store.del_lswitch('id3', 'topic2')
        self.assertIsNone(self.db_store.get_lswitch('id3'))

    def test_port(self):
        port1 = mock.Mock()
        port2 = mock.Mock()
        port2.get_lswitch_id.return_value = 'net1'
        port3 = mock.Mock()
        port3.get_lswitch_id.return_value = 'net1'
        port4 = mock.Mock()
        port4.get_id.return_value = 'port_id3'
        self.db_store.set_port('id1', port1, False, 'topic1')
        self.db_store.set_port('id2', port2, False, 'topic2')
        self.db_store.set_port('id3', port3, False, 'topic2')
        self.db_store.set_port('id4', port4, True, 'topic2')
        port_keys = self.db_store.get_port_keys()
        port_keys_topic2 = self.db_store.get_port_keys('topic2')
        self.assertEqual({'id1', 'id2', 'id3', 'id4'}, set(port_keys))
        self.assertIn('id2', port_keys_topic2)
        self.assertIn('id3', port_keys_topic2)
        ports = self.db_store.get_ports()
        ports_topic2 = self.db_store.get_ports('topic2')
        self.assertEqual({port1, port2, port3, port4}, set(ports))
        self.assertIn(port2, ports_topic2)
        self.assertIn(port3, ports_topic2)
        self.assertEqual(port1, self.db_store.get_port('id1'))
        self.assertEqual(port2, self.db_store.get_port('id2'))
        self.assertEqual(
            port1,
            self.db_store.get_port('id1', 'topic1'),
        )
        self.assertIsNone(self.db_store.get_local_port('id1'))
        self.assertIsNone(self.db_store.get_local_port('id2', 'topic2'))
        self.assertEqual(
            port4,
            self.db_store.get_local_port('id4', 'topic2')
        )
        self.assertEqual(
            port4,
            self.db_store.get_local_port_by_name('tapport_id3')
        )
        self.db_store.delete_port('id4', True, 'topic2')
        self.assertIsNone(
            self.db_store.get_local_port('id4', 'topic2')
        )
        self.assertIsNone(
            self.db_store.get_port('id4', 'topic2')
        )
        self.assertEqual(
            {port2, port3},
            set(self.db_store.get_ports_by_network_id('net1'))
        )
        self.db_store.delete_port('id3', False, 'topic2')
        self.assertIsNone(self.db_store.get_port('id3'))

    def test_router(self):
        router1 = mock.Mock()
        port1_1 = mock.Mock()
        port1_1.get_mac.return_value = '12:34:56:78:90:ab'
        router1.get_ports.return_value = [port1_1]
        router2 = mock.Mock()
        router2.get_ports.return_value = [mock.Mock()]
        router3 = mock.Mock()
        router3.get_ports.return_value = [mock.Mock(), mock.Mock()]
        self.db_store.update_router('id1', router1, 'topic1')
        self.db_store.update_router('id2', router2, 'topic2')
        self.db_store.update_router('id3', router3, 'topic2')
        self.assertEqual(router1, self.db_store.get_router('id1'))
        self.assertEqual(router2, self.db_store.get_router('id2'))
        self.assertEqual(
            router1,
            self.db_store.get_router('id1', 'topic1'),
        )
        self.assertIn(router2, self.db_store.get_routers('topic2'))
        self.assertIn(router3, self.db_store.get_routers('topic2'))
        self.assertEqual(
            {router1, router2, router3},
            set(self.db_store.get_routers()),
        )
        self.assertEqual(
            router1,
            self.db_store.get_router_by_router_interface_mac(
                '12:34:56:78:90:ab'
            )
        )
        self.db_store.delete_router('id3', 'topic2')
        self.assertIsNone(self.db_store.get_router('id3'))

    def test_security_group(self):
        sg1 = 'sg1'
        sg2 = 'sg2'
        sg3 = 'sg3'
        self.db_store.update_security_group('id1', sg1, 'topic1')
        self.db_store.update_security_group('id2', sg2, 'topic2')
        self.db_store.update_security_group('id3', sg3, 'topic2')
        self.assertEqual(sg1, self.db_store.get_security_group('id1'))
        self.assertEqual(sg2, self.db_store.get_security_group('id2'))
        self.assertEqual(
            sg3,
            self.db_store.get_security_group('id3', 'topic2')
        )
        sg_keys = self.db_store.get_security_group_keys()
        sg_keys_topic2 = self.db_store.get_security_group_keys('topic2')
        sgs = self.db_store.get_security_groups()
        sgs_topic2 = self.db_store.get_security_groups('topic2')
        self.assertEqual({'id1', 'id2', 'id3'}, set(sg_keys))
        self.assertIn('id2', sg_keys_topic2)
        self.assertIn('id3', sg_keys_topic2)
        self.assertEqual({sg1, sg2, sg3}, set(sgs))
        self.assertIn(sg2, sgs_topic2)
        self.assertIn(sg3, sgs_topic2)
        self.db_store.delete_security_group('id3', 'topic2')
        self.assertIsNone(self.db_store.get_security_group('id3', 'topic2'))

    def test_floating_ip(self):
        fip1 = 'fip1'
        fip2 = 'fip2'
        fip3 = 'fip3'
        self.db_store.update_floatingip('id1', fip1, 'topic1')
        self.db_store.update_floatingip('id2', fip2, 'topic2')
        self.db_store.update_floatingip('id3', fip3, 'topic2')
        self.assertEqual(fip1, self.db_store.get_floatingip('id1'))
        self.assertEqual(fip2, self.db_store.get_floatingip('id2'))
        self.assertEqual(
            fip3,
            self.db_store.get_floatingip('id3', 'topic2')
        )
        fips = self.db_store.get_floatingips()
        fips_topic2 = self.db_store.get_floatingips('topic2')
        self.assertEqual({fip1, fip2, fip3}, set(fips))
        self.assertIn(fip2, fips_topic2)
        self.assertIn(fip3, fips_topic2)
        self.db_store.delete_floatingip('id3', 'topic2')
        self.assertIsNone(self.db_store.get_floatingip('id3', 'topic2'))

    def test_publisher(self):
        pub1 = mock.Mock()
        pub1.get_topic.return_value = None
        pub2 = mock.Mock()
        pub2.get_topic.return_value = None
        pub3 = mock.Mock()
        pub3.get_topic.return_value = None
        self.db_store.update_publisher('id1', pub1)
        self.db_store.update_publisher('id2', pub2)
        self.db_store.update_publisher('id3', pub3)
        self.assertEqual(pub1, self.db_store.get_publisher('id1'))
        self.assertEqual(pub2, self.db_store.get_publisher('id2'))
        self.assertEqual(pub3, self.db_store.get_publisher('id3'))
        self.db_store.delete_publisher('id3')
        self.assertIsNone(self.db_store.get_publisher('id3'))

    def test_chassis(self):
        chassis1 = mock.Mock()
        chassis1.get_id.return_value = "chassis1"
        chassis2 = mock.Mock()
        chassis2.get_id.return_value = "chassis2"
        self.db_store.update_chassis('chassis1', chassis1)
        self.db_store.update_chassis('chassis2', chassis2)
        self.assertEqual(chassis1, self.db_store.get_chassis('chassis1'))
        self.assertEqual(chassis2, self.db_store.get_chassis('chassis2'))
        self.assertIsNone(self.db_store.get_chassis('chassis3'))

        self.db_store.delete_chassis('chassis2')
        self.assertIsNone(self.db_store.get_chassis('chassis2'))
