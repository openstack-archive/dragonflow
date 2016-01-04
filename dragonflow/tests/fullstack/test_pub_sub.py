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


from dragonflow.db import api_nb
from dragonflow.db import db_publisher
from dragonflow.db import db_subscriber
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

        subscriber = db_subscriber.SubscriberAgent(
                                        '127.0.0.1',
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

        subscriber = db_subscriber.SubscriberAgent(
                                        '127.0.0.1',
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

    def test_pub_sub_event_number(self):
        global events_num

        def _db_change_callback(table, key, action, value):
            global events_num
            events_num += 1

        db_ip = '127.0.0.1'
        publiser = db_publisher.PublisherAgent(
                                    db_ip,
                                    is_plugin=False,
                                    publish_port=6666)
        publiser.daemonize()
        subscriber = db_subscriber.SubscriberAgent(
                                        db_ip,
                                        _db_change_callback,
                                        plugin_port=6666,
                                        cont_port=6667)
        subscriber.daemonize()
        eventlet.sleep(2)
        local_events_num = events_num
        update = api_nb.DbUpdate("test", "key", "action", "value")
        publiser.send_event(update)
        eventlet.sleep(1)

        self.assertEqual(local_events_num + 1, events_num)
        subscriber.stop()
        publiser.stop()
