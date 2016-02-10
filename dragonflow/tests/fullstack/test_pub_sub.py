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


class Namespace(object):
    pass


class TestPubSub(test_base.DFTestBase):

    def setUp(self):
        super(TestPubSub, self).setUp()
        self.events_num = 0
        self.do_test = cfg.CONF.df.use_df_pub_sub

    def test_pub_sub_add_port(self):
        global events_num
        local_event_num = 0

        if not self.do_test:
            return

        def _db_change_callback(table, key, action, value):
            global events_num
            events_num += 1
        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        subscriber = pub_sub_driver.get_subscriber()
        subscriber.initialize(_db_change_callback)
        uri = 'tcp://%s:%s' % ('127.0.0.1',
                cfg.CONF.df.publisher_port)
        subscriber.register_listen_address(uri)

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
        ns = Namespace()
        ns.events_num = 0
        local_event_num = 0

        if not self.do_test:
            return

        def _db_change_callback(table, key, action, value):
            ns.events_num += 1

        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        subscriber = pub_sub_driver.get_subscriber()

        subscriber.initialize(_db_change_callback)
        uri = 'tcp://%s:%s' % ('127.0.0.1',
                    cfg.CONF.df.publisher_port)
        subscriber.register_listen_address(uri)

        subscriber.daemonize()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, ns.events_num)
        port = {'admin_state_up': True, 'name': 'port1',
                'network_id': network_id}
        local_event_num = ns.events_num
        port = self.neutron.create_port(body={'port': port})
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, ns.events_num)
        local_event_num = ns.events_num
        update = {'port': {'name': 'test'}}
        for i in six.moves.range(100):
            name = "test %d" % i
            update['port']['name'] = name
            port = self.neutron.update_port(port['port']['id'], update)
            eventlet.sleep(0)
        eventlet.sleep(1)
        self.assertGreaterEqual(ns.events_num, local_event_num + 100)
        local_event_num = ns.events_num
        self.neutron.delete_port(port['port']['id'])
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, ns.events_num)
        local_event_num = ns.events_num
        network.delete()
        eventlet.sleep(1)
        self.assertNotEqual(local_event_num, events_num)
        subscriber.stop()
        self.assertFalse(network.exists())

    def test_pub_sub_event_number_diffrent_port(self):
        self.events_num = 0
        self.events_action = 0

        def _db_change_callback(table, key, action, value):
            self.events_num += 1
            self.events_action = action

        publisher_ip = '127.0.0.1'
        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        publisher = pub_sub_driver.get_publisher()
        subscriber = pub_sub_driver.get_subscriber()

        subscriber.initialize(_db_change_callback)
        uri = 'tcp://%s:%s' % (publisher_ip, 6666)
        subscriber.register_listen_address(uri)

        subscriber.daemonize()

        endpoint = '*:%s' % 6666
        cfg.CONF.df.publisher_port = 6666
        publisher.initialize(
                    multiprocessing_queue=False,
                    endpoint=endpoint,
                    trasport_proto='tcp',
                    config=cfg.CONF.df)

        publisher.daemonize()
        eventlet.sleep(2)
        local_events_num = self.events_num
        action = "test_action"
        update = api_nb.DbUpdate("test", "key", action, "value")
        publisher.send_event(update)
        eventlet.sleep(1)

        self.assertEqual(local_events_num + 1, self.events_num)
        self.assertEqual(self.events_action, action)
        subscriber.stop()
        publisher.stop()

    def test_pub_sub_add_topic(self):
        self.events_num_t = 0
        self.events_action_t = None

        def _db_change_callback_topic(table, key, action, value):
            self.events_num_t += 1
            self.events_action_t = action

        pub_sub_driver = df_utils.load_driver(
                                cfg.CONF.df.pub_sub_driver,
                                df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        publisher = pub_sub_driver.get_publisher()
        subscriber = pub_sub_driver.get_subscriber()

        publisher_ip = '127.0.0.1'
        endpoint = '*:%s' % 7777
        cfg.CONF.df.publisher_port = 7777
        publisher.initialize(
                            multiprocessing_queue=False,
                            endpoint=endpoint,
                            trasport_proto='tcp',
                            config=cfg.CONF.df)
        subscriber.initialize(_db_change_callback_topic)
        uri = 'tcp://%s:%s' % (publisher_ip, 7777)
        subscriber.register_listen_address(uri)

        subscriber.daemonize()
        publisher.daemonize()
        eventlet.sleep(2)
        topic = "topic"
        subscriber.register_topic(topic)
        eventlet.sleep(0.5)
        local_events_num = self.events_num_t
        action = "test_action"
        update = api_nb.DbUpdate("test", "key", action, "value")
        publisher.send_event(update, topic)
        eventlet.sleep(1)
        self.assertEqual(self.events_action_t, action)
        self.assertEqual(local_events_num + 1, self.events_num_t)
        no_topic_action = "no topic"
        other_topic = "Other-topic"
        self.events_action_t = None
        update = api_nb.DbUpdate("test", "key", no_topic_action, "value")
        publisher.send_event(update, other_topic)
        eventlet.sleep(1)

        self.assertEqual(self.events_action_t, None)
        self.assertNotEqual(local_events_num + 2, self.events_num_t)
        subscriber.unregister_topic(topic)
        publisher.send_event(update, topic)
        self.assertEqual(self.events_action_t, None)
        subscriber.stop()
        publisher.stop()
