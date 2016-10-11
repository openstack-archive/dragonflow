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
from oslo_config import cfg

from dragonflow.tests.unit import test_app_base


class TestTopology(test_app_base.DFAppTestBase):
    # This is to comply the current code, as the app_list can't be empty.
    # But we don't need any app in this test, acutally.
    apps_list = "l2_ml2_app.L2App"

    def setUp(self):
        cfg.CONF.set_override('enable_selective_topology_distribution',
                              True, group='df')
        cfg.CONF.set_override('enable_port_status_notifier', False, group='df')
        super(TestTopology, self).setUp(enable_selective_topo_dist=True)
        # By default, return empty value for all resources, each case can
        # customize the return value on their own.
        self.nb_api.get_all_logical_switches.return_value = []
        self.nb_api.get_all_logical_ports.return_value = []
        self.nb_api.get_routers.return_value = []
        self.nb_api.get_security_groups.return_value = []
        self.nb_api.get_floatingips.return_value = []

    def test_vm_port_online_offline(self):
        self.nb_api.get_all_logical_switches.return_value = [
            test_app_base.fake_logic_switch1]
        self.nb_api.get_all_logical_ports.return_value = [
            test_app_base.fake_local_port1]
        self.nb_api.get_logical_port.return_value = (
            test_app_base.fake_local_port1)

        # Verify port online
        original_update = self.controller.logical_port_updated
        self.controller.logical_port_updated = mock.Mock()
        self.controller.logical_port_updated.side_effect = original_update

        self.topology.ovs_port_updated(test_app_base.fake_ovs_port1)

        self.controller.logical_port_updated.assert_called_once_with(
            test_app_base.fake_local_port1)
        self.nb_api.subscriber.register_topic.assert_called_once_with(
            test_app_base.fake_local_port1.get_topic())

        # Verify port offline
        self.nb_api.get_all_logical_ports.return_value = []
        original_delete = self.controller.logical_port_deleted
        self.controller.logical_port_deleted = mock.Mock()
        self.controller.logical_port_deleted.side_effect = original_delete

        self.topology.ovs_port_deleted(test_app_base.fake_ovs_port1.get_id())

        self.controller.logical_port_deleted.assert_called_once_with(
            test_app_base.fake_local_port1.get_id())
        self.nb_api.subscriber.unregister_topic.assert_called_once_with(
            test_app_base.fake_local_port1.get_topic())

    def test_vm_online_after_topology_pulled(self):
        self.nb_api.get_all_logical_switches.return_value = [
            test_app_base.fake_logic_switch1]
        self.nb_api.get_all_logical_ports.return_value = [
            test_app_base.fake_local_port1]

        def _get_logical_port(lport_id, topic):
            if lport_id == test_app_base.fake_local_port1.get_id():
                return test_app_base.fake_local_port1
            if lport_id == test_app_base.fake_local_port2.get_id():
                return test_app_base.fake_local_port2

        self.nb_api.get_logical_port.side_effect = _get_logical_port

        # Pull topology by first ovs port online
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port1)

        # Another port online
        self.nb_api.get_all_logical_ports.return_value = [
            test_app_base.fake_local_port1,
            test_app_base.fake_local_port2]
        self.controller.logical_port_updated = mock.Mock()
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port2)
        self.controller.logical_port_updated.assert_called_once_with(
            test_app_base.fake_local_port2)
        self.assertEqual(1, self.nb_api.subscriber.register_topic.call_count)

    def test_multi_vm_port_online_restart_controller(self):
        self.nb_api.get_all_logical_switches.return_value = [
            test_app_base.fake_logic_switch1]
        self.nb_api.get_all_logical_ports.return_value = [
            test_app_base.fake_local_port1,
            test_app_base.fake_local_port2]

        def _get_logical_port(lport_id, topic):
            if lport_id == test_app_base.fake_local_port1.get_id():
                return test_app_base.fake_local_port1
            if lport_id == test_app_base.fake_local_port2.get_id():
                return test_app_base.fake_local_port2

        self.nb_api.get_logical_port.side_effect = _get_logical_port
        original_update = self.controller.logical_port_updated
        self.controller.logical_port_updated = mock.Mock()
        self.controller.logical_port_updated.side_effect = original_update

        # The vm ports are online one by one
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port1)
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port2)

        calls = [mock.call(test_app_base.fake_local_port1),
                 mock.call(test_app_base.fake_local_port2)]
        self.controller.logical_port_updated.assert_has_calls(
            calls, any_order=True)
        self.assertEqual(2, self.controller.logical_port_updated.call_count)
        self.assertEqual(1, self.nb_api.subscriber.register_topic.call_count)

    def test_check_topology_info(self):
        topic = 'fake_tenant1'
        lport_id2 = '2'
        ovs_port_id2 = 'ovs_port2'
        lport_id3 = '3'
        ovs_port_id3 = 'ovs_port3'

        self.topology.ovs_to_lport_mapping = {
            ovs_port_id2: {
                'lport_id': lport_id2,
                'topic': topic
            },
            ovs_port_id3: {
                'lport_id': lport_id3,
                'topic': topic
            }
        }
        self.topology.ovs_ports = {
            'fake_ovs_port1': test_app_base.fake_ovs_port1
        }
        self.topology.topic_subscribed = {
            topic: {lport_id2, lport_id3}
        }
        self.controller.db_store.set_port(
            test_app_base.fake_local_port1.get_id(),
            test_app_base.fake_local_port1, True, topic)
        self.topology.check_topology_info()
        self.assertEqual(1, len(self.topology.topic_subscribed[topic]))
