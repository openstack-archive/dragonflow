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
from neutron.i18n import _LI, _LW

from dragonflow.common import common_params
from dragonflow.controller import dispatcher
from dragonflow.db import api_nb
from dragonflow.db import db_store
from dragonflow.db.drivers import ovsdb_vswitch_impl

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
        self.dispatcher = dispatcher.AppDispatcher('dragonflow.controller',
                                                   cfg.CONF.df.apps_list,
                                                   kwargs)

    def run(self):
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(nb_driver_class())
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)
        self.vswitch_api = ovsdb_vswitch_impl.OvsdbSwitchApi(self.ip)
        self.vswitch_api.initialize()

        self.dispatcher.load()
        self.dispatcher.is_ready()

        self.db_sync_loop()

    def db_sync_loop(self):
        while True:
            time.sleep(1)
            self.run_db_poll()
            if self.sync_finished and (
                    self.nb_api.support_publish_subscribe()):
                self.nb_api.wait_for_db_changes(self)

    def run_db_poll(self):
        try:
            self.nb_api.sync()

            self.vswitch_api.sync()

            self.register_chassis()

            self.create_tunnels()

            self.read_switches()

            self.port_mappings()

            self.read_routers()

            self.sync_finished = True

        except Exception as e:
            self.sync_finished = False
            LOG.warn(_LW("run_db_poll - suppressing exception"))
            LOG.warn(e)

    def chassis_created(self, chassis):
        # Check if tunnel already exists to this chassis

        # Create tunnel port to this chassis
        LOG.info(_LI("Adding tunnel to remote chassis"))
        LOG.info(chassis.__str__())
        self.vswitch_api.add_tunnel_port(chassis)

    def chassis_deleted(self, chassis_id):
        LOG.info(_LI("Deleting tunnel to remote chassis %s") % chassis_id)
        tunnel_ports = self.vswitch_api.get_tunnel_ports()
        for port in tunnel_ports:
            if port.get_chassis_id() == chassis_id:
                self.vswitch_api.delete_port(port)
                return

    def read_switches(self):
        for lswitch in self.nb_api.get_all_logical_switches():
            self.logical_switch_updated(lswitch)

    def logical_switch_updated(self, lswitch):
        old_lswitch = self.db_store.get_lswitch(lswitch.get_id())
        if old_lswitch == lswitch:
            return
        LOG.info(_LI("Adding/Updating Logical Switch"))
        LOG.info(lswitch.__str__())
        self.db_store.set_lswitch(lswitch.get_id(), lswitch)
        self.dispatcher.dispatch('logical_switch_updated', lswitch=lswitch)

    def logical_switch_deleted(self, lswitch_id):
        LOG.info(_LI("Removing Logical Switch %s") % lswitch_id)
        self.db_store.del_lswitch(lswitch_id)
        self.dispatcher.dispatch('logical_switch_deleted',
                                 lswitch_id=lswitch_id)

    def logical_port_updated(self, lport):
        if self.db_store.get_port(lport.get_id()) is not None:
            # TODO(gsagie) support updating port
            return

        if lport.get_chassis() is None:
            return

        chassis_to_ofport, lport_to_ofport = (
            self.vswitch_api.get_local_ports_to_ofport_mapping())
        network = self.get_network_id(lport.get_lswitch_id())
        lport.set_external_value('local_network_id', network)

        if lport.get_chassis() == self.chassis_name:
            ofport = lport_to_ofport.get(lport.get_id(), 0)
            if ofport != 0:
                lport.set_external_value('ofport', ofport)
                lport.set_external_value('is_local', True)
                LOG.info(_LI("Adding new local Logical Port"))
                LOG.info(lport.__str__())
                self.dispatcher.dispatch('add_local_port', lport=lport)
                self.db_store.set_port(lport.get_id(), lport, True)
            else:
                raise RuntimeError("ofport is 0")
        else:
            ofport = chassis_to_ofport.get(lport.get_chassis(), 0)
            if ofport != 0:
                lport.set_external_value('ofport', ofport)
                lport.set_external_value('is_local', False)
                LOG.info(_LI("Adding new remote Logical Port"))
                LOG.info(lport.__str__())
                self.dispatcher.dispatch('add_remote_port', lport=lport)
                self.db_store.set_port(lport.get_id(), lport, False)
            else:
                raise RuntimeError("ofport is 0")

    def logical_port_deleted(self, lport_id):
        lport = self.db_store.get_port(lport_id)
        if lport is None:
            return
        if lport.get_external_value('is_local'):
            LOG.info(_LI("Removing local Logical Port"))
            LOG.info(lport.__str__())
            self.dispatcher.dispatch('remove_local_port', lport=lport)
            self.db_store.delete_port(lport.get_id(), True)
        else:
            LOG.info(_LI("Removing remote Logical Port"))
            LOG.info(lport.__str__())
            self.dispatcher.dispatch('remove_remote_port', lport=lport)
            self.db_store.delete_port(lport.get_id(), False)

    def router_updated(self, lrouter):
        old_lrouter = self.db_store.get_router(lrouter.get_name())
        if old_lrouter is None:
            LOG.info(_LI("Logical Router created"))
            LOG.info(lrouter.__str__())
            self._add_new_lrouter(lrouter)
            return
        self._update_router_interfaces(old_lrouter, lrouter)
        self.db_store.update_router(lrouter.get_name(), lrouter)

    def router_deleted(self, lrouter_id):
        pass

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
            self.vswitch_api.delete_port(port)

    def port_mappings(self):
        ports_to_remove = self.db_store.get_port_keys()
        for lport in self.nb_api.get_all_logical_ports():
            self.logical_port_updated(lport)
            if lport.get_id() in ports_to_remove:
                ports_to_remove.remove(lport.get_id())

        for port_to_remove in ports_to_remove:
            self.logical_port_deleted(port_to_remove)

    def get_network_id(self, logical_dp_id):
        network_id = self.db_store.get_network_id(logical_dp_id)
        if network_id is not None:
            return network_id
        else:
            self.next_network_id += 1
            # TODO(gsagie) verify self.next_network_id didnt wrap
            self.db_store.set_network_id(logical_dp_id, self.next_network_id)

    def read_routers(self):
        for lrouter in self.nb_api.get_routers():
            self.router_updated(lrouter)

    def _update_router_interfaces(self, old_router, new_router):
        new_router_ports = new_router.get_ports()
        old_router_ports = old_router.get_ports()
        for new_port in new_router_ports:
            if new_port not in old_router_ports:
                self._add_new_router_port(new_router, new_port)
            else:
                old_router_ports.remove(new_port)

        for old_port in old_router_ports:
            self._delete_router_port(old_port)

    def _add_new_router_port(self, router, router_port):
        LOG.info(_LI("Adding new logical router interface"))
        LOG.info(router_port.__str__())
        local_network_id = self.db_store.get_network_id(
            router_port.get_lswitch_id())
        self.dispatcher.dispatch('add_new_router_port', router=router,
                                 router_port=router_port,
                                 local_network_id=local_network_id)

    def _delete_router_port(self, router_port):
        LOG.info(_LI("Removing logical router interface"))
        LOG.info(router_port.__str__())
        local_network_id = self.db_store.get_network_id(
            router_port.get_lswitch_id())
        self.dispatcher.dispatch('delete_router_port',
                                 router_port=router_port,
                                 local_network_id=local_network_id)

    def _add_new_lrouter(self, lrouter):
        for new_port in lrouter.get_ports():
            self._add_new_router_port(lrouter, new_port)
        self.db_store.update_router(lrouter.get_name(), lrouter)


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
