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

from dragonflow.controller.ryu_base_app import RyuDFAdapter
from dragonflow.tests import base as tests_base
from oslo_config import cfg


class TestRyuDFAdapter(tests_base.BaseTestCase):
    """
    This unit test has to verify that all events are called correctly, both
    via the notify* functions, as well as the events called from ryu.

    Having ryu call these events will be done in the functional tests.
    """
    def setUp(self):
        super(TestRyuDFAdapter, self).setUp()
        self.db_store = mock.Mock()
        cfg.CONF = mock.Mock()
        self.ryu_df_adapter = RyuDFAdapter(db_store=self.db_store)
        self.mock_app = mock.Mock(spec=[
                'update_logical_switch',
                'remove_logical_switch',
                'add_local_port',
                'remove_local_port',
                'add_remote_port',
                'remove_remote_port',
                'add_router_port',
                'remove_router_port',
                'add_security_group_rule',
                'remove_security_group_rule',
                'switch_features_handler',
                'port_desc_stats_reply_handler',
                'packet_in_handler'
        ])

        def dispatcher_load(*args, **kwargs):
            self.ryu_df_adapter.dispatcher.apps = [self.mock_app]
        self.ryu_df_adapter.dispatcher.load = dispatcher_load
        self.ryu_df_adapter.load()

    def test_notifies(self):
        self.mock_app.reset_mock()
        self.ryu_df_adapter.notify_update_logical_switch(lswitch=1)
        self.ryu_df_adapter.notify_remove_logical_switch(lswitch=2)
        self.ryu_df_adapter.notify_add_local_port(lport=3)
        self.ryu_df_adapter.notify_remove_local_port(lport=4)
        self.ryu_df_adapter.notify_add_remote_port(lport=5)
        self.ryu_df_adapter.notify_remove_remote_port(lport=6)
        self.ryu_df_adapter.notify_add_router_port(
                router=7, router_port=8, local_network_id=9)
        self.ryu_df_adapter.notify_remove_router_port(
                router_port=10, local_network_id=11)
        self.ryu_df_adapter.notify_add_security_group_rule(
                secgroup=12, secgroup_rule=13)
        self.ryu_df_adapter.notify_remove_security_group_rule(
                secgroup=14, secgroup_rule=15)
        self.mock_app.assert_has_calls([
                mock.call.update_logical_switch(lswitch=1),
                mock.call.remove_logical_switch(lswitch=2),
                mock.call.add_local_port(lport=3),
                mock.call.remove_local_port(lport=4),
                mock.call.add_remote_port(lport=5),
                mock.call.remove_remote_port(lport=6),
                mock.call.add_router_port(
                        local_network_id=9, router=7, router_port=8),
                mock.call.remove_router_port(
                        local_network_id=11, router_port=10),
                mock.call.add_security_group_rule(
                        secgroup=12, secgroup_rule=13),
                mock.call.remove_security_group_rule(
                        secgroup=14, secgroup_rule=15)])

    def test_switch_features_handler(self):
        self.mock_app.reset_mock()
        ev = mock.Mock()
        self.ryu_df_adapter.switch_features_handler(ev)
        self.mock_app.assert_has_calls([mock.call.switch_features_handler(ev)])

    def test_port_desc_stats_reply_handler(self):
        self.mock_app.reset_mock()
        ev = mock.Mock()
        self.ryu_df_adapter.port_desc_stats_reply_handler(ev)
        self.mock_app.assert_has_calls([
                mock.call.port_desc_stats_reply_handler(ev)])

    def test_port_status_handler(self):
        self.mock_app.reset_mock()
        ev = mock.Mock()
        ev.msg.reason = ev.msg.datapath.ofproto.OFPPR_ADD
        self.ryu_df_adapter._port_status_handler(ev)
        port_name = ev.msg.desc.name
        lport = self.db_store.get_local_port_by_name(port_name)
        self.mock_app.assert_has_calls([mock.call.add_local_port(lport=lport)])
        lport.assert_has_calls([
                mock.call.set_external_value('ofport', ev.msg.desc.port_no),
                mock.call.set_external_value('is_local', True)])

        self.mock_app.reset_mock()
        ev = mock.Mock()
        ev.msg.reason = ev.msg.datapath.ofproto.OFPPR_DELETE
        self.ryu_df_adapter._port_status_handler(ev)
        port_name = ev.msg.desc.name
        lport = self.db_store.get_local_port_by_name(port_name)
        self.mock_app.assert_has_calls([
                mock.call.remove_local_port(lport=lport)])
        #TODO(oanson) Once notification is added, add update_local_port test

    def test_packet_in_handler(self):
        self.mock_app.reset_mock()
        ev = mock.Mock()
        ev.msg.table_id = 10
        self.ryu_df_adapter.register_table_handler(
                10, self.mock_app.packet_in_handler)
        self.ryu_df_adapter.OF_packet_in_handler(ev)
        self.mock_app.assert_has_calls([mock.call.packet_in_handler(ev)])
