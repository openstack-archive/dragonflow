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

import logging
from mock import Mock
import sys

import ryu.ofproto.ofproto_v1_3_parser as parser

from dragonflow.controller.common import constants as const
from dragonflow.controller.l3_proactive_app import L3ProactiveApp
from dragonflow.db.api_nb import LogicalRouter, LogicalPort, LogicalSwitch
from dragonflow.db.db_store import DbStore
from dragonflow.tests import base as tests_base

logger = logging.getLogger()
logger.level = logging.DEBUG
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)


class TestL3ProactiveApp(tests_base.BaseTestCase):

    def setUp(self):
        super(TestL3ProactiveApp, self).setUp()
        self.db_store = DbStore()
        self.mock_api = Mock(name="api")
        self.mock_nb_api = Mock(name="nb_api")
        self.mock_vswitch_api = Mock(name="vswitch_api")

        mock_datapath = Mock(name="datapath", ofproto_parser=parser)
        mock_api = Mock(name='api')
        self.mock_mod_flow = Mock(name='mod_flow')
        mock_api.get_datapatch.return_value = mock_datapath

        self.app = L3ProactiveApp(self.mock_api, self.db_store,
                                  self.mock_vswitch_api,
                                  self.mock_nb_api)
        self.app.mod_flow = self.mock_mod_flow

        self.ri_port_value = '''
            {
                "name": "ri_port",
                "chassis": "test_chassis",
                "admin_state": "True",
                "ips": ["192.168.10.1"],
                "macs": ["112233445566"],
                "lswitch": "lswitch1",
                "topic": "tenant1",
                "tunnel_key": 1025
            }
            '''
        self.nexthop_port_value = '''
            {
                "name": "nexthop_port",
                "chassis": "test_chassis",
                "admin_state": "True",
                "ips": ["192.168.10.254"],
                "macs": ["112233445577"],
                "lswitch": "lswitch1",
                "topic": "tenant1",
                "tunnel_key": 1024
            }
            '''

        self.lswitch1_value = '''
            {
                "name": "lswitch1",
                "subnets": [
                    {
                        "topic": "tenant1",
                        "gateway_ip": "192.168.10.1",
                        "cidr": "192.168.10.0/24",
                        "id": "subnet1",
                        "name": "subnet1"
                    }
                ]
            }
        '''

        self.router_value = '''
            {
                "name": "router1",
                "topic": "tenant1",
                "version": "1.0",
                "ports": [
                    {
                        "network": "192.168.10.0/24",
                        "lswitch": "lswitch1",
                        "topic": "tenant1",
                        "id": "ri_port"
                    }
                ]
            }
            '''

        self.route1 = {"destination": "10.100.0.0/16",
                       "nexthop": "192.168.10.254"}

        self.ri_port = LogicalPort(self.ri_port_value)
        self.nexthop_port = LogicalPort(self.nexthop_port_value)
        self.lswitch1 = LogicalSwitch(self.lswitch1_value)
        self.router1 = LogicalRouter(self.router_value)
        self.db_store.set_port('ri_port', self.ri_port, False, 'tenant1')
        self.db_store.set_port('nexthop_port', self.nexthop_port,
                               False, 'tenant1')
        self.db_store.set_lswitch('lswitch1', self.lswitch1, 'tenant1')

    def test_add_route(self):
        self.app.add_router_route(self.router1, self.route1)
        assert self.mock_mod_flow.called
        args, kwargs = self.mock_mod_flow.call_args
        assert kwargs['cookie'] == 1024
        assert kwargs['table_id'] == const.L3_LOOKUP_TABLE
        assert len(kwargs['inst']) == 2

    def test_del_route(self):
        self.test_add_route()
        self.app.remove_router_route(self.router1, self.route1)
        assert len(self.mock_mod_flow.call_args_list) == 2
        args, kwargs = self.mock_mod_flow.call_args
        assert kwargs['table_id'] == const.L3_LOOKUP_TABLE
        assert 'out_port' in kwargs
        assert 'out_group' in kwargs
