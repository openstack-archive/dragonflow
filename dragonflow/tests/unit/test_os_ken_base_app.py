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

import testtools
from unittest import mock

from dragonflow import conf as cfg
from dragonflow.switch.drivers.ovs import os_ken_base_app
from dragonflow.tests import base as tests_base


class TestOsKenDFAdapter(tests_base.BaseTestCase):
    """
    This unit test has to verify that all events are called correctly, both
    via the notify* functions, as well as the events called from os_ken.

    Having os_ken call these events will be done in the functional tests.
    """
    def setUp(self):
        super(TestOsKenDFAdapter, self).setUp()
        cfg.CONF.set_override(
            'datapath_layout_path',
            'etc/dragonflow_datapath_layout.yaml',
            group='df',
        )
        self.os_ken_df_adapter = os_ken_base_app.OsKenDFAdapter(
            switch_backend=mock.Mock(),
            nb_api=mock.Mock(),
            db_change_callback=mock.Mock())
        self.mock_app = mock.Mock(spec=[
                'router_updated',
                'router_deleted',
                'add_security_group_rule',
                'remove_security_group_rule',
                'switch_features_handler',
                'port_desc_stats_reply_handler',
                'packet_in_handler'
        ])

        def dispatcher_load(*args, **kwargs):
            self.os_ken_df_adapter.dispatcher.apps = {'mock': self.mock_app}
        self.os_ken_df_adapter.dispatcher.load = dispatcher_load
        self.os_ken_df_adapter.load()

    def test_switch_features_handler(self):
        self.mock_app.reset_mock()
        ev = mock.Mock()
        ev.msg = mock.Mock()
        ev.msg.datapath = mock.Mock()
        ev.msg.datapath.ofproto = mock.Mock()
        ev.msg.datapath.ofproto.OFP_VERSION = 0x04
        self.os_ken_df_adapter.switch_features_handler(ev)
        self.mock_app.assert_has_calls([mock.call.switch_features_handler(ev)])

    def test_port_desc_stats_reply_handler(self):
        self.mock_app.reset_mock()
        ev = mock.Mock()
        self.os_ken_df_adapter.port_desc_stats_reply_handler(ev)
        self.mock_app.assert_has_calls([
                mock.call.port_desc_stats_reply_handler(ev)])

    def test_packet_in_handler(self):
        self.mock_app.reset_mock()
        ev = mock.Mock()
        ev.msg.table_id = 10
        self.mock_app.packet_in_handler.__name__ = 'mock'
        self.os_ken_df_adapter.register_table_handler(
                10, self.mock_app.packet_in_handler)
        self.os_ken_df_adapter.OF_packet_in_handler(ev)
        self.mock_app.assert_has_calls([mock.call.packet_in_handler(ev)])

    def test_register_twice(self):
        self.os_ken_df_adapter.register_table_handler(0, 0)
        with testtools.ExpectedException(RuntimeError):
            self.os_ken_df_adapter.register_table_handler(0, 0)
