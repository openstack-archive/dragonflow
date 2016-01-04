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

import eventlet
import six

from oslo_config import cfg

from dragonflow.common import utils as df_utils
from dragonflow.db import api_nb
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


events_num = 0


class TestPubSub(test_base.DFTestBase):

    def setUp(self):
        super(TestPubSub, self).setUp()
        self.events_num = 0

    def test_pub_sub_add_port(self):
        global events_num
        local_event_num = 0

        def _db_change_callback(table, key, action, value):
            global events_num
            events_num += 1
        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        subscriber = pub_sub_driver.get_subscriber()
        subscriber.initialize('127.0.0.1',
                            _db_change_callback,
                            plugin_port=8866,
                            cont_port=8867)

        subscriber.daemonize()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        port = {'admin_state_up': True, 'name': 'port1',
                'network_id': network_id}
        local_event_num = events_num
        port = self.neutron.create_port(body={'port': port})
        eventlet.sleep(1)

        self.assertNotEqual(local_event_num, events_num)
        local_event_num = events_num
        self.neutron.delete_port(port['port']['id'])
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        local_event_num = events_num
        network.delete()
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        subscriber.stop()
        self.assertFalse(network.exists())

    def test_pub_sub_update_port(self):
        global events_num
        local_event_num = 0

        def _db_change_callback(table, key, action, value):
            global events_num
            events_num += 1
        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        subscriber = pub_sub_driver.get_subscriber()

        subscriber.initialize('127.0.0.1',
                            _db_change_callback,
                            plugin_port=8866,
                            cont_port=8867)

        subscriber.daemonize()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        port = {'admin_state_up': True, 'name': 'port1',
                'network_id': network_id}
        local_event_num = events_num
        port = self.neutron.create_port(body={'port': port})
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        local_event_num = events_num
        update = {'port': {'name': 'test'}}
        for i in six.moves.range(100):
            name = "test %d" % i
            update['port']['name'] = name
            port = self.neutron.update_port(port['port']['id'], update)
            eventlet.sleep(0)
        eventlet.sleep(1)
        self.assertGreaterEqual(events_num, local_event_num + 100)
        local_event_num = events_num
        self.neutron.delete_port(port['port']['id'])
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        local_event_num = events_num
        network.delete()
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        subscriber.stop()
        self.assertFalse(network.exists())

    def test_pub_sub_event_number_plugin_port(self):
        self.events_num_p = 0
        self.events_action_p = 0

        def _db_change_callback(table, key, action, value):
            self.events_num_p += 1
            self.events_action_p = action

        db_ip = '127.0.0.1'
        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        publiser = pub_sub_driver.get_publisher()
        subscriber = pub_sub_driver.get_subscriber()

        publiser.initialize(db_ip,
                            is_neutron_server=False,
                            publish_port=6664)
        publiser.daemonize()
        subscriber.initialize(db_ip,
                            _db_change_callback,
                            plugin_port=6664,
                            cont_port=6665)
        subscriber.daemonize()
        eventlet.sleep(2)
        action = "test_action"
        local_events_num = self.events_num_p
        update = api_nb.DbUpdate("test", "key", action, "value")
        publiser.send_event(update)
        eventlet.sleep(1)

        self.assertEqual(local_events_num + 1, self.events_num_p)
        self.assertEqual(self.events_action_p, action)
        publiser.stop()
        subscriber.stop()

    def test_pub_sub_event_number_controller_port(self):
        self.events_num = 0
        self.events_action = 0

        def _db_change_callback(table, key, action, value):
            self.events_num += 1
            self.events_action = action

        db_ip = '127.0.0.1'
        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        publiser = pub_sub_driver.get_publisher()
        subscriber = pub_sub_driver.get_subscriber()

        publiser.initialize(db_ip,
                            is_neutron_server=False,
                            publish_port=6667)
        publiser.daemonize()
        subscriber.initialize(db_ip,
                            _db_change_callback,
                            plugin_port=6666,
                            cont_port=6667)
        subscriber.daemonize()
        eventlet.sleep(2)
        local_events_num = self.events_num
        action = "test_action"
        update = api_nb.DbUpdate("test", "key", action, "value")
        publiser.send_event(update)
        eventlet.sleep(1)

        self.assertEqual(local_events_num + 1, self.events_num)
        self.assertEqual(self.events_action, action)
        publiser.stop()
        subscriber.stop()

    def test_pub_sub_add_topic(self):
        self.events_num_t = 0
        self.events_action_t = None

        def _db_change_callback_topic(table, key, action, value):
            self.events_num_t += 1
            self.events_action_t = action

        db_ip = '127.0.0.1'
        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        publiser = pub_sub_driver.get_publisher()
        subscriber = pub_sub_driver.get_subscriber()

        publiser.initialize(db_ip,
                            is_neutron_server=False,
                            publish_port=7777)
        publiser.daemonize()
        subscriber.initialize(db_ip,
                            _db_change_callback_topic,
                            plugin_port=7777,
                            cont_port=7778)
        subscriber.daemonize()
        eventlet.sleep(2)
        topic = "topic"
        subscriber.add_topic(topic)
        eventlet.sleep(0.5)
        local_events_num = self.events_num_t
        action = "test_action"
        update = api_nb.DbUpdate("test", "key", action, "value")
        publiser.send_event(update, topic)
        eventlet.sleep(1)
        self.assertEqual(self.events_action_t, action)
        self.assertEqual(local_events_num + 1, self.events_num_t)
        no_topic_action = "no topic"
        other_topic = "Other-topic"
        self.events_action_t = None
        update = api_nb.DbUpdate("test", "key", no_topic_action, "value")
        publiser.send_event(update, other_topic)
        eventlet.sleep(1)

        self.assertEqual(self.events_action_t, None)
        self.assertNotEqual(local_events_num + 2, self.events_num_t)
        publiser.stop()
        subscriber.stop()
