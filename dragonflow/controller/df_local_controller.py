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


import sys
import time

import eventlet
from oslo_log import log

from ryu.base.app_manager import AppManager
from ryu.controller.ofp_handler import OFPHandler

from dragonflow.controller.l2_app import L2App
from dragonflow.db.drivers import ovsdb_nb_impl, ovsdb_vswitch_impl

#from dragonflow.db.drivers import etcd_nb_impl

LOG = log.getLogger(__name__)

eventlet.monkey_patch()


class DfLocalController(object):

    def __init__(self, chassis_name, ip, remote_db_ip):
        self.l3_app = None
        self.l2_app = None
        self.open_flow_app = None
        self.next_network_id = 0
        self.networks = {}
        self.ports = {}
        self.nb_api = None
        self.vswitch_api = None
        self.chassis_name = chassis_name
        self.ip = ip
        self.remote_db_ip = remote_db_ip

    def run(self):
        self.nb_api = ovsdb_nb_impl.OvsdbNbApi(self.remote_db_ip)
        #self.nb_api = etcd_nb_impl.EtcdNbApi()
        self.nb_api.initialize()
        self.vswitch_api = ovsdb_vswitch_impl.OvsdbSwitchApi(self.ip)
        self.vswitch_api.initialize()

        app_mgr = AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(OFPHandler, None, None)
        self.open_flow_app.start()
        self.l2_app = app_mgr.instantiate(L2App, None, None)
        self.l2_app.start()
        self.db_sync_loop()

    def db_sync_loop(self):
        while True:
            time.sleep(3)
            self.run_db_poll()

    def run_db_poll(self):
        try:
            self.nb_api.sync()

            self.read_routers()

            self.vswitch_api.sync()

            self.register_chassis()

            self.create_tunnels()

            self.set_binding()

            self.port_mappings()
        except Exception:
            pass

    def register_chassis(self):
        chassis = self.nb_api.get_chassis(self.chassis_name)
        # TODO(gsagie) Support tunnel type change here ?

        if chassis is None:
            self.nb_api.add_chassis(self.chassis_name,
                                    self.ip,
                                    'geneve')

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
                self.vswitch_api.add_tunnel_port(chassis)

        # Iterate all tunnel ports that needs to be deleted
        for port in tunnel_ports.values():
            self.vswitch_api.delete_port(port)

    def set_binding(self):
        local_ports = self.vswitch_api.get_local_port_ids()
        self.nb_api.register_local_ports(self.chassis_name, local_ports)

    def port_mappings(self):
        chassis_to_ofport, lport_to_ofport = (
            self.vswitch_api.get_local_ports_to_ofport_mapping())

        ports_to_remove = set(self.ports.keys())

        for lport in self.nb_api.get_all_logical_ports():
            network = self.get_network_id(lport.get_network_id())
            lport.set_external_value('local_network_id', network)

            if lport.get_chassis() == self.chassis_name:
                ofport = lport_to_ofport.get(lport.get_id(), 0)
                if ofport != 0:
                    lport.set_external_value('ofport', ofport)
                    lport.set_external_value('is_local', True)
                    self.ports[lport.get_id()] = lport
                    if lport.get_id() in ports_to_remove:
                        ports_to_remove.remove(lport.get_id())
                    self.l2_app.add_local_port(lport.get_id(),
                                               lport.get_mac(),
                                               network,
                                               ofport,
                                               lport.get_tunnel_key())
            else:
                ofport = chassis_to_ofport.get(lport.get_chassis(), 0)
                if ofport != 0:
                    lport.set_external_value('ofport', ofport)
                    lport.set_external_value('is_local', False)
                    self.ports[lport.get_id()] = lport
                    if lport.get_id() in ports_to_remove:
                        ports_to_remove.remove(lport.get_id())
                    self.l2_app.add_remote_port(lport.get_id(),
                                                lport.get_mac(),
                                                network,
                                                ofport,
                                                lport.get_tunnel_key())

        # TODO(gsagie) use port dictionary in all methods in l2 app
        # and here instead of always moving all arguments
        for port_to_remove in ports_to_remove:
            p = self.ports[port_to_remove]
            if p.get_external_value('is_local'):
                self.l2_app.remove_local_port(p.get_id(),
                                              p.get_mac(),
                                              p.get_external_value(
                                                  'local_network_id'),
                                              p.get_external_value(
                                                  'ofport'),
                                              p.get_tunnel_key())
                del self.ports[port_to_remove]
            else:
                self.l2_app.remove_remote_port(p.get_id(),
                                               p.get_mac(),
                                               p.get_external_value(
                                                   'local_network_id'),
                                               p.get_tunnel_key())
                del self.ports[port_to_remove]

    def get_network_id(self, logical_dp_id):
        network_id = self.networks.get(logical_dp_id)
        if network_id is not None:
            return network_id
        else:
            self.next_network_id += 1
            # TODO(gsagie) verify self.next_network_id didnt wrap
            self.networks[logical_dp_id] = self.next_network_id

    def read_routers(self):
        for lrouter in self.nb_api.get_routers():
            pass


# Run this application like this:
# python df_local_controller.py <chassis_unique_name>
# <local ip address> <southbound_db_ip_address>
def main():
    chassis_name = sys.argv[1]  # unique name 'df_chassis'
    ip = sys.argv[2]  # local ip '10.100.100.4'
    remote_db_ip = sys.argv[3]  # remote SB DB IP '10.100.100.4'
    controller = DfLocalController(chassis_name, ip, remote_db_ip)
    controller.run()

if __name__ == "__main__":
    main()
