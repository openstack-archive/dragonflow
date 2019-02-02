# Copyright (c) 2018 OpenStack Foundation
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

from os_ken.app.ofctl import service as of_service
from os_ken.base import app_manager
from os_ken import cfg as os_ken_cfg

from dragonflow import conf as cfg
from dragonflow.controller import datapath_layout
from dragonflow.db.models import l2
from dragonflow.db.models import switch
from dragonflow.ovsdb import vswitch_impl
from dragonflow.switch.drivers import df_switch_driver
from dragonflow.switch.drivers.ovs import datapath
from dragonflow.switch.drivers.ovs import os_ken_base_app


class DfOvsDriver(df_switch_driver.DfSwitchDriver):
    def __init__(self, nb_api, ip):
        super(DfOvsDriver, self).__init__(nb_api)
        init_os_ken_config()
        self.vswitch_api = vswitch_impl.OvsApi(ip)
        self.app_mgr = app_manager.AppManager.get_instance()
        self.open_flow_app = None
        self.open_flow_service = None
        self.neutron_notifier = None
        self._datapath = datapath.Datapath(
            datapath_layout.get_datapath_layout())

    def initialize(self, db_change_callback, neutron_notifier):
        super(DfOvsDriver, self).initialize(db_change_callback,
                                            neutron_notifier)
        self.open_flow_app = self.app_mgr.instantiate(
            os_ken_base_app.OsKenDFAdapter,
            nb_api=self.nb_api,
            switch_backend=self,
            neutron_server_notifier=self.neutron_notifier,
            db_change_callback=self.db_change_callback
        )
        # The OfctlService is needed to support the 'get_flows' method
        self.open_flow_service = self.app_mgr.instantiate(
            of_service.OfctlService)

    def setup_datapath(self, df_app):
        self._datapath.set_up(df_app, self,
                              self.nb_api, self.neutron_notifier)

    @property
    def datapath(self):
        return self._datapath

    def start(self):
        self.vswitch_api.initialize(self.db_change_callback)
        # both set_controller and del_controller will delete flows.
        # for reliability, here we should check if controller is set for OVS,
        # if yes, don't set controller and don't delete controller.
        # if no, set controller
        targets = ('tcp:' + cfg.CONF.df_os_ken.of_listen_address + ':' +
                   str(cfg.CONF.df_os_ken.of_listen_port))
        is_controller_set = self.vswitch_api.check_controller(targets)
        integration_bridge = cfg.CONF.df.integration_bridge
        if not is_controller_set:
            self.vswitch_api.set_controller(integration_bridge, [targets])
        is_fail_mode_set = self.vswitch_api.check_controller_fail_mode(
            'secure')
        if not is_fail_mode_set:
            self.vswitch_api.set_controller_fail_mode(integration_bridge,
                                                      'secure')
        self.open_flow_service.start()
        self.open_flow_app.start()

    def stop(self):
        pass

    def switch_sync_started(self):
        self.open_flow_app.notify_switch_sync_started()

    def switch_sync_finished(self):
        self.open_flow_app.notify_switch_sync_finished()

    def sync_ignore_models(self):
        return [switch.SwitchPort, ]

    def notify_port_status(self, switch_port, status):
        if self.neutron_notifier:
            table_name = l2.LogicalPort.table_name
            iface_id = switch_port.lport
            self.neutron_notifier.notify_neutron_server(table_name, iface_id,
                                                        'update', status)


def init_os_ken_config():
    os_ken_cfg.CONF(project='os_ken', args=[])
    os_ken_cfg.CONF.ofp_listen_host = cfg.CONF.df_os_ken.of_listen_address
    os_ken_cfg.CONF.ofp_tcp_listen_port = cfg.CONF.df_os_ken.of_listen_port
