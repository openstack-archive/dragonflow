# Copyright (c) 2017 Huawei Tech. Co., Ltd. .
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
from ryu.base import app_manager
from ryu import cfg as ryu_cfg
import time

from dragonflow import conf as cfg
from dragonflow.controller import ryu_base_app
from dragonflow.ovsdb import vswitch_impl
from dragonflow.tests.common import constants as const
from dragonflow.tests.fullstack import test_base


class TestRyuBaseApp(test_base.DFTestBase):
    def setUp(self):
        super(TestRyuBaseApp, self).setUp()
        ryu_cfg.CONF(project='ryu', args=[])
        ryu_cfg.CONF.ofp_listen_host = cfg.CONF.df_ryu.of_listen_address
        ryu_cfg.CONF.ofp_tcp_listen_port = cfg.CONF.df_ryu.of_listen_port + 1
        app_mgr = app_manager.AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(ryu_base_app.RyuDFAdapter)
        self.open_flow_app.load = mock.Mock()
        self.addCleanup(app_mgr.uninstantiate, self.open_flow_app.name)

        test_controller = ('tcp:' + cfg.CONF.df_ryu.of_listen_address + ':' +
            str(cfg.CONF.df_ryu.of_listen_port + 1))
        self.vswitch_api = vswitch_impl.OvsApi(self.mgt_ip)
        self.vswitch_api.initialize(self.nb_api)
        cur_controllers = self.vswitch_api.ovsdb.get_controller(
            self.integration_bridge).execute()
        cur_controllers.append(test_controller)
        self.vswitch_api.set_controller(self.integration_bridge,
                                        cur_controllers)

        cur_controllers.pop()
        self.addCleanup(self.vswitch_api.set_controller,
                        self.integration_bridge, cur_controllers)

        self.open_flow_app.start()
        time.sleep(const.DEFAULT_CMD_TIMEOUT)

    def test_TTL_set_in_packet_in_mask(self):
        with mock.patch.object(self.open_flow_app,
                               'set_sw_async_msg_config_for_ttl') as m:
            self.open_flow_app.get_sw_async_msg_config()
            time.sleep(const.DEFAULT_CMD_TIMEOUT)
            ofproto = self.open_flow_app.datapath.ofproto
            self.assertTrue(m.called)
            current_config = m.call_args_list[0][0][0]
            # Make sure the ttl mask has already been set.
            self.assertEqual(1 << ofproto.OFPR_INVALID_TTL,
                             (current_config.packet_in_mask[0] &
                              1 << ofproto.OFPR_INVALID_TTL))
