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

import copy

import mock
from oslo_config import cfg

from dragonflow.controller import topology
from dragonflow.tests.common import utils
from dragonflow.tests.unit import test_app_base


def nb_api_get_all_func(*instances):
    """
    Create an method that can be used to override the mock's nb_api's get_all
    to return objects that should exist, e.g. instances that were created
    with create (and verified with the relevant assert)
    :param instances:   An iterable of instances that should exist in nb_api
    :type instances:    iterable of instances
    """
    alls = {}
    for instance in instances:
        try:
            alls[instance.__class__].append(instance)
        except KeyError:
            alls[instance.__class__] = [instance]

    def nb_api_get_all(inst, topic=None):
        try:
            if not topic:
                return alls[inst]
            return [obj for obj in alls[inst] if obj.topic == topic]
        except KeyError:
            return mock.MagicMock(name='NbApi.get_instance().get()')
    return nb_api_get_all


class TestTopology(test_app_base.DFAppTestBase):
    # This is to comply the current code, as the app_list can't be empty.
    # But we don't need any app in this test, acutally.
    apps_list = ["l2"]

    def setUp(self):
        cfg.CONF.set_override('enable_selective_topology_distribution',
                              True, group='df')
        cfg.CONF.set_override('enable_neutron_notifier', False, group='df')
        super(TestTopology, self).setUp(enable_selective_topo_dist=True)
        # By default, return empty value for all resources, each case can
        # customize the return value on their own.
        self.nb_api.get_all.return_value = []
        self.fake_invalid_ovs_port = copy.deepcopy(
            test_app_base.fake_ovs_port1)
        self.controller._register_models()

    @utils.with_nb_objects(
        test_app_base.fake_chassis1,
        test_app_base.fake_local_port1,
        test_app_base.fake_logic_switch1,
    )
    def test_vm_port_online_offline(self):
        original_update = self.controller.update
        self.controller.update = mock.Mock()
        self.controller.update.side_effect = original_update
        self.controller._sync._update_cb = self.controller.update

        original_delete = self.controller.delete
        self.controller.delete = mock.Mock()
        self.controller.delete.side_effect = original_delete
        self.controller._sync._delete_cb = self.controller.delete

        original_delete_by_id = self.controller.delete_by_id
        self.controller.delete_by_id = mock.Mock()
        self.controller.delete_by_id.side_effect = original_delete_by_id

        # Verify port online
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port1)
        self.controller.update.assert_has_calls(
            (mock.call(test_app_base.fake_logic_switch1),
             mock.call(test_app_base.fake_local_port1)),
        )
        self.nb_api.subscriber.register_topic.assert_called_once_with(
            test_app_base.fake_local_port1.topic)

        # Verify port offline
        self.controller.delete.reset_mock()
        self.controller.update.reset_mock()
        self.nb_api.get_all.return_value = []
        self.topology.ovs_port_deleted(test_app_base.fake_ovs_port1)
        self.controller.delete.assert_has_calls([
            mock.call(test_app_base.fake_local_port1),
            mock.call(test_app_base.fake_logic_switch1),
        ])
        self.nb_api.subscriber.unregister_topic.assert_called_once_with(
            test_app_base.fake_local_port1.topic)

        self.fake_invalid_ovs_port.ofport = -1
        self.controller.update.reset_mock()
        self.topology.ovs_port_updated(self.fake_invalid_ovs_port)
        self.controller.update.assert_not_called()

    def test_vm_online_after_topology_pulled(self):
        self.nb_api.get_all.side_effect = nb_api_get_all_func(
            test_app_base.fake_logic_switch1,
            test_app_base.fake_local_port1,
            test_app_base.fake_chassis1,
        )
        self.nb_api.get.return_value = test_app_base.fake_local_port1
        # Pull topology by first ovs port online
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port1)

        # Another port online
        self.nb_api.get_all.side_effect = nb_api_get_all_func(
            test_app_base.fake_logic_switch1,
            test_app_base.fake_local_port1,
            test_app_base.fake_local_port2,
            test_app_base.fake_chassis1,
        )
        self.controller.update = mock.Mock()
        self.nb_api.get.return_value = test_app_base.fake_local_port2
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port2)
        self.controller.update.assert_called_once_with(
            test_app_base.fake_local_port2)
        self.nb_api.subscriber.register_topic.assert_called_once()

    def test_multi_vm_port_online_restart_controller(self):
        self.nb_api.get_all.side_effect = nb_api_get_all_func(
            test_app_base.fake_logic_switch1,
            test_app_base.fake_local_port1,
            test_app_base.fake_local_port2,
            test_app_base.fake_chassis1,
        )

        def _get_logical_port(lport):
            lport_id = lport.id
            if lport_id == test_app_base.fake_local_port1.id:
                return test_app_base.fake_local_port1
            if lport_id == test_app_base.fake_local_port2.id:
                return test_app_base.fake_local_port2

        self.nb_api.get.side_effect = _get_logical_port
        original_update = self.controller.update
        self.controller.update = mock.Mock()
        self.controller.update.side_effect = original_update
        self.controller._sync._update_cb = self.controller.update

        # The vm ports are online one by one
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port1)
        self.topology.ovs_port_updated(test_app_base.fake_ovs_port2)

        calls = [mock.call(test_app_base.fake_chassis1),
                 mock.call(test_app_base.fake_logic_switch1),
                 mock.call(test_app_base.fake_local_port1),
                 mock.call(test_app_base.fake_local_port2)]
        self.controller.update.assert_has_calls(
            calls, any_order=True)
        self.assertEqual(4, self.controller.update.call_count)
        self.nb_api.subscriber.register_topic.assert_called_once()

    def test_check_topology_info(self):
        topic = 'fake_tenant1'
        lport_id2 = '2'
        ovs_port_id2 = 'ovs_port2'
        lport_id3 = '3'
        ovs_port_id3 = 'ovs_port3'

        self.topology.ovs_to_lport_mapping = {
            ovs_port_id2: topology.OvsLportMapping(
                lport_id=lport_id2,
                topic=topic
            ),
            ovs_port_id3: topology.OvsLportMapping(
                lport_id=lport_id3,
                topic=topic
            )
        }
        self.topology.ovs_ports = {
            'fake_ovs_port1': test_app_base.fake_ovs_port1
        }
        self.topology.topic_subscribed = {
            topic: {lport_id2, lport_id3}
        }
        self.controller.db_store.update(test_app_base.fake_local_port1)
        self.topology.check_topology_info()
        self.assertEqual(1, len(self.topology.topic_subscribed[topic]))

    def test_db_sync(self):
        self.nb_api.get_all.side_effect = nb_api_get_all_func(
            test_app_base.fake_logic_switch1,
            test_app_base.fake_local_port1)

        self.topology.topic_subscribed = {
            'fake_tenant1': test_app_base.fake_local_port1}
        update = mock.Mock()
        self.controller._sync._topics = {'fake_tenant1'}
        self.controller._sync._update_cb = update

        # Verify the db sync will work for topology
        self.controller.sync()
        update_calls = [
            mock.call(test_app_base.fake_logic_switch1),
            mock.call(test_app_base.fake_local_port1)
        ]
        update.assert_has_calls(update_calls)
        self.assertEqual(2, update.call_count)
