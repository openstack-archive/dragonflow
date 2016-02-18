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

import socket
import sys
import time

import eventlet

from oslo_config import cfg
from oslo_log import log
from oslo_utils import importutils

from neutron.agent.common import config
from neutron.common import config as common_config

from dragonflow._i18n import _LI, _LW
from dragonflow.common import common_params
from dragonflow.common import constants
from dragonflow.controller.ryu_base_app import RyuDFAdapter
from dragonflow.controller.topology import Topology
from dragonflow.db import api_nb
from dragonflow.db import db_store
from dragonflow.db.drivers import ovsdb_vswitch_impl

from ryu.base.app_manager import AppManager

config.setup_logging()
LOG = log.getLogger("dragonflow.controller.df_local_controller")

eventlet.monkey_patch()

cfg.CONF.register_opts(common_params.df_opts, 'df')


class DfLocalController(object):

    def __init__(self, chassis_name):
        self.next_network_id = 0
        self.db_store = db_store.DbStore()
        self.nb_api = None
        self.vswitch_api = None
        self.chassis_name = chassis_name
        self.ip = cfg.CONF.df.local_ip
        self.tunnel_type = cfg.CONF.df.tunnel_type
        self.sync_finished = False
        kwargs = dict(
            db_store=self.db_store
        )
        app_mgr = AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(RyuDFAdapter, **kwargs)

        self.topology = None

    def run(self):
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(
                nb_driver_class(),
                use_pubsub=cfg.CONF.df.enable_df_pub_sub)
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)
        self.vswitch_api = ovsdb_vswitch_impl.OvsdbSwitchApi(self.ip)
        self.vswitch_api.initialize()

        self.topology = Topology(self)

        self.vswitch_api.sync()
        self.vswitch_api.del_controller('br-int').execute()
        self.vswitch_api.set_controllers(
            'br-int', ['tcp:' + self.ip + ':6633']).execute()

        self.open_flow_app.start()
        self.db_sync_loop()

    def db_sync_loop(self):
        while True:
            time.sleep(1)
            self.run_db_poll()
            if self.sync_finished and (
                    self.nb_api.support_publish_subscribe()):
                self.nb_api.register_notification_callback(self.topology)

    def run_sync(self):
        self.sync_finished = True
        while True:
            time.sleep(1)
            self.run_db_poll()
            if self.sync_finished:
                return

    def run_db_poll(self):
        try:
            self.nb_api.sync()

            self.vswitch_api.sync()

            self.register_chassis()

            self.create_tunnels()

            #self.read_switches()

            #self.read_security_groups()

            #self.port_mappings()

            #self.read_routers()

            self.sync_finished = True

        except Exception as e:
            self.sync_finished = False
            LOG.warning(_LW("run_db_poll - suppressing exception"))
            LOG.warning(e)

    def register_chassis(self):
        chassis = self.nb_api.get_chassis(self.chassis_name)
        # TODO(gsagie) Support tunnel type change here ?

        if chassis is None:
            self.nb_api.add_chassis(self.chassis_name,
                                    self.ip,
                                    self.tunnel_type)

    def create_tunnels(self):
        tunnel_ports = {}
        t_ports = self.vswitch_api.get_tunnel_ports()
        for t_port in t_ports:
            tunnel_ports[t_port.get_chassis_id()] = t_port

        for chassis in self.nb_api.get_all_chassis():
            if chassis.get_name() in tunnel_ports:
                del tunnel_ports[chassis.get_name()]
            elif chassis.get_name() == self.chassis_name:
                pass
            else:
                self.chassis_created(chassis)

        # Iterate all tunnel ports that needs to be deleted
        for port in tunnel_ports.values():
            self.vswitch_api.delete_port(port).execute()

    def get_open_flow_app(self):
        return self.open_flow_app

    def get_nb_api(self):
        return self.nb_api

    def get_db_store(self):
        return self.db_store

    def get_chassis_name(self):
        return self.chassis_name

    def get_vswitch_api(self):
        return self.vswitch_api


# Run this application like this:
# python df_local_controller.py <chassis_unique_name>
# <local ip address> <southbound_db_ip_address>
def main():
    chassis_name = socket.gethostname()
    common_config.init(sys.argv[1:])
    controller = DfLocalController(chassis_name)
    controller.run()

if __name__ == "__main__":
    main()
