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
import random
import six

from neutron.agent.linux.utils import wait_until_true
from oslo_config import cfg
from oslo_serialization import jsonutils

from dragonflow.common import utils as df_utils
from dragonflow.db import db_common
from dragonflow.db import pub_sub_api
from dragonflow.tests.common import utils as test_utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


events_num = 0


def get_publisher():
    if cfg.CONF.df.pub_sub_use_multiproc:
        pubsub_driver_name = cfg.CONF.df.pub_sub_multiproc_driver
    else:
        pubsub_driver_name = cfg.CONF.df.pub_sub_driver
    pub_sub_driver = df_utils.load_driver(
        pubsub_driver_name,
        df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
    publisher = pub_sub_driver.get_publisher()
    publisher.initialize()
    return publisher


def get_server_publisher():
    cfg.CONF.df.publisher_port = "12345"
    cfg.CONF.df.publisher_bind_address = "127.0.0.1"
    pub_sub_driver = df_utils.load_driver(
        cfg.CONF.df.pub_sub_driver,
        df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
    publisher = pub_sub_driver.get_publisher()
    publisher.initialize()
    return publisher


def get_subscriber(callback):
    pub_sub_driver = df_utils.load_driver(
        cfg.CONF.df.pub_sub_driver,
        df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
    subscriber = pub_sub_driver.get_subscriber()
    subscriber.initialize(callback)
    subscriber.register_topic(db_common.SEND_ALL_TOPIC)
    uri = '%s://%s:%s' % (
        cfg.CONF.df.publisher_transport,
        '127.0.0.1',
        cfg.CONF.df.publisher_port
    )
    subscriber.register_listen_address(uri)
    subscriber.daemonize()
    return subscriber


class Namespace(object):
    pass


class TestPubSub(test_base.DFTestBase):

    def setUp(self):
        super(TestPubSub, self).setUp()
        self.events_num = 0
        self.do_test = cfg.CONF.df.enable_df_pub_sub
        self.key = 'key-{}'.format(random.random())

    def test_pub_sub_add_port(self):
        global events_num
        local_event_num = 0

        if not self.do_test:
            return

        def _db_change_callback(table, key, action, value, topic):
            global events_num
            events_num += 1
        subscriber = get_subscriber(_db_change_callback)
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        if cfg.CONF.df.enable_selective_topology_distribution:
            topic = network.get_topic()
            subscriber.register_topic(topic)
        else:
            eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
            self.assertNotEqual(local_event_num, events_num)
            local_event_num = events_num
        port = self.store(objects.PortTestObj(
            self.neutron,
            self.nb_api,
            network_id
        ))
        port.create()
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)

        self.assertNotEqual(local_event_num, events_num)
        local_event_num = events_num
        port.close()
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        self.assertNotEqual(local_event_num, events_num)
        local_event_num = events_num
        network.close()
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        self.assertNotEqual(local_event_num, events_num)
        if cfg.CONF.df.enable_selective_topology_distribution:
            subscriber.unregister_topic(topic)
        subscriber.stop()
        self.assertFalse(network.exists())

    def test_pub_sub_update_port(self):
        ns = Namespace()
        ns.events_num = 0
        local_event_num = 0

        if not self.do_test:
            return

        def _db_change_callback(table, key, action, value, topic):
            ns.events_num += 1

        subscriber = get_subscriber(_db_change_callback)
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        if cfg.CONF.df.enable_selective_topology_distribution:
            topic = network.get_topic()
            subscriber.register_topic(topic)
        else:
            eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
            self.assertNotEqual(local_event_num, ns.events_num)
        port = self.store(objects.PortTestObj(
            self.neutron,
            self.nb_api,
            network_id
        ))
        local_event_num = ns.events_num
        port_id = port.create()
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        self.assertNotEqual(local_event_num, ns.events_num)
        local_event_num = ns.events_num
        update = {'port': {'name': 'test'}}
        for i in six.moves.range(100):
            name = "test %d" % i
            update['port']['name'] = name
            self.neutron.update_port(port_id, update)
            eventlet.sleep(0)
        eventlet.sleep(1)
        self.assertGreaterEqual(ns.events_num, local_event_num + 100)
        local_event_num = ns.events_num
        port.close()
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        self.assertNotEqual(local_event_num, ns.events_num)
        local_event_num = ns.events_num
        network.close()
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        self.assertNotEqual(local_event_num, events_num)
        if cfg.CONF.df.enable_selective_topology_distribution:
            subscriber.unregister_topic(topic)
        subscriber.stop()
        self.assertFalse(network.exists())

    def test_pub_sub_event_number_different_port(self):
        if not self.do_test:
            return

        ns = Namespace()
        ns.events_num = 0
        ns.events_action = None

        def _db_change_callback(table, key, action, value, topic):
            if 'log' == key:
                ns.events_num += 1
                ns.events_action = action

        publisher = get_publisher()
        subscriber = get_subscriber(_db_change_callback)

        eventlet.sleep(2)
        local_events_num = ns.events_num
        action = "log"
        update = db_common.DbUpdate(
            'info', 'log', action, "test ev no diff ports value")
        publisher.send_event(update)
        eventlet.sleep(1)

        self.assertEqual(local_events_num + 1, ns.events_num)
        self.assertEqual(ns.events_action, action)
        local_events_num = ns.events_num
        for i in six.moves.range(100):
            publisher.send_event(update)
            eventlet.sleep(0.01)
        eventlet.sleep(1)

        self.assertEqual(local_events_num + 100, ns.events_num)
        subscriber.stop()

    def test_pub_sub_add_topic(self):
        if not self.do_test:
            return

        self.events_num_t = 0
        self.events_action_t = None

        def _db_change_callback_topic(table, key, action, value, topic):
            if 'log' == key:
                self.events_num_t += 1
                self.events_action_t = action

        publisher = get_publisher()
        subscriber = get_subscriber(_db_change_callback_topic)
        eventlet.sleep(2)
        topic = "topic"
        subscriber.register_topic(topic)
        eventlet.sleep(0.5)
        local_events_num = self.events_num_t
        action = "log"
        update = db_common.DbUpdate(
            'info',
            'log',
            action,
            "test_pub_sub_add_topic value"
        )
        publisher.send_event(update, topic)
        eventlet.sleep(1)
        self.assertEqual(self.events_action_t, action)
        self.assertEqual(local_events_num + 1, self.events_num_t)
        no_topic_action = 'log'
        other_topic = "Other-topic"
        self.events_action_t = None
        update = db_common.DbUpdate(
            'info', None, no_topic_action, "No topic value")
        publisher.send_event(update, other_topic)
        eventlet.sleep(1)

        self.assertIsNone(self.events_action_t)
        self.assertNotEqual(local_events_num + 2, self.events_num_t)
        subscriber.unregister_topic(topic)
        publisher.send_event(update, topic)
        self.assertIsNone(self.events_action_t)
        subscriber.stop()

    def test_pub_sub_register_addr(self):
        if not self.do_test:
            return
        ns = Namespace()
        ns.events_num = 0
        ns.events_action = None

        def _db_change_callback(table, key, action, value, topic):
            if 'log' == key:
                ns.events_num += 1
                ns.events_action = action

        publisher = get_publisher()
        subscriber = get_subscriber(_db_change_callback)
        eventlet.sleep(2)
        action = "log"
        update = db_common.DbUpdate(
            'info',
            'log',
            action,
            "value"
        )
        update.action = action
        update.topic = db_common.SEND_ALL_TOPIC
        publisher.send_event(update)
        eventlet.sleep(1)
        self.assertEqual(ns.events_action, action)

        publisher2 = get_server_publisher()
        uri = '%s://%s:%s' % (
                cfg.CONF.df.publisher_transport,
                '127.0.0.1',
                cfg.CONF.df.publisher_port)
        subscriber.register_listen_address(uri)
        eventlet.sleep(2)
        update.action = action
        update.topic = db_common.SEND_ALL_TOPIC
        ns.events_action = None
        publisher2.send_event(update)
        eventlet.sleep(1)
        self.assertEqual(ns.events_action, action)


class TestMultiprocPubSub(test_base.DFTestBase):

    def setUp(self):
        super(TestMultiprocPubSub, self).setUp()
        self.do_test = cfg.CONF.df.enable_df_pub_sub
        self.key = 'key-{}'.format(random.random())
        self.event = db_common.DbUpdate(
            'info',
            None,
            "log",
            "TestMultiprocPubSub value",
            topic=db_common.SEND_ALL_TOPIC,
        )
        self.subscriber = None

    def tearDown(self):
        if self.subscriber:
            self.subscriber.stop()
        super(TestMultiprocPubSub, self).tearDown()

    def _verify_event(self, table, key, action, value, topic):
        self.assertEqual(self.event.table, table)
        self.assertEqual(self.event.key, key)
        self.assertEqual(self.event.action, action)
        # Value is not tested, since it's currently set to None
        # self.assertEqual(self.event.value, value)
        self.assertEqual(self.event.topic, topic)
        self.event_received = True

    def test_multiproc_pub_sub(self):
        if not self.do_test:
            return
        self.event_received = False
        cfg.CONF.df.publisher_multiproc_socket = '/tmp/ipc_test_socket'
        pub_sub_driver = df_utils.load_driver(
            cfg.CONF.df.pub_sub_multiproc_driver,
            df_utils.DF_PUBSUB_DRIVER_NAMESPACE)
        publisher = pub_sub_driver.get_publisher()
        publisher.initialize()
        self.subscriber = pub_sub_driver.get_subscriber()
        self.subscriber.initialize(self._verify_event)
        self.subscriber.daemonize()
        publisher.send_event(self.event)
        wait_until_true(lambda: self.event_received)
        self.subscriber.stop()
        self.subscriber = None


class TestDbTableMonitors(test_base.DFTestBase):
    def setUp(self):
        super(TestDbTableMonitors, self).setUp()
        self.events_num = 0
        enable_df_pub_sub = cfg.CONF.df.enable_df_pub_sub
        self.do_test = enable_df_pub_sub
        if not self.do_test:
            return
        self.namespace = Namespace()
        self.namespace.events = []
        self.namespace.has_values = False
        self.publisher = get_publisher()
        self.subscriber = get_subscriber(self._db_change_callback)
        self.monitor = self._create_monitor('chassis')

    def tearDown(self):
        if self.do_test:
            self.monitor.stop()
            self.subscriber.stop()
        super(TestDbTableMonitors, self).tearDown()

    def _db_change_callback(self, table, key, action, value, topic):
        self.namespace.events.append({
            'table': table,
            'key': key,
            'action': action,
            'value': value,
        })
        if value:
            self.namespace.has_values = True

    def _create_monitor(self, table_name):
        table_monitor = pub_sub_api.TableMonitor(
            table_name,
            self.nb_api.driver,
            self.publisher,
            1,
        )
        table_monitor.daemonize()
        return table_monitor

    def test_operations(self):
        if not self.do_test:
            return

        test_chassis = {
            "ip": "1.2.3.4",
            "id": "chassis-1",
            "tunnel_type": "geneve"
        }

        expected_event = {
            'table': unicode('chassis'),
            'key': unicode('chassis-1'),
            'action': unicode('create'),
            'value': None,
        }
        self.assertNotIn(expected_event, self.namespace.events)
        expected_event['value'] = unicode(jsonutils.dumps(test_chassis))
        self.assertNotIn(expected_event, self.namespace.events)
        self.nb_api.driver.create_key(
            'chassis',
            'chassis-1',
            jsonutils.dumps(test_chassis))
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        if not self.namespace.has_values:
            expected_event['value'] = None
        self.assertIn(expected_event, self.namespace.events)

        test_chassis["ip"] = "2.3.4.5"
        expected_event = {
            'table': unicode('chassis'),
            'key': unicode('chassis-1'),
            'action': unicode('set'),
            'value': None,
        }
        self.assertNotIn(expected_event, self.namespace.events)
        expected_event['value'] = unicode(jsonutils.dumps(test_chassis))
        self.assertNotIn(expected_event, self.namespace.events)
        self.nb_api.driver.set_key(
            'chassis',
            'chassis-1',
            jsonutils.dumps(test_chassis))
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        if not self.namespace.has_values:
            expected_event['value'] = None
        self.assertIn(expected_event, self.namespace.events)

        expected_event = {
            'table': unicode('chassis'),
            'key': unicode('chassis-1'),
            'action': unicode('delete'),
            'value': None,
        }
        self.assertNotIn(expected_event, self.namespace.events)
        self.nb_api.driver.delete_key('chassis', 'chassis-1')
        eventlet.sleep(test_utils.DEFAULT_CMD_TIMEOUT)
        self.assertIn(expected_event, self.namespace.events)
