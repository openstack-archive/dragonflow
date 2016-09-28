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

from neutron.agent.common import config
from neutron.common import config as common_config
from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from ryu.base import app_manager
from ryu import cfg as ryu_cfg
from ryu.ofproto import ofproto_common

from dragonflow._i18n import _LI, _LW, _
from dragonflow.common import common_params
from dragonflow.common import constants
from dragonflow.common import utils as df_utils
from dragonflow.controller import ryu_base_app
from dragonflow.controller import topology
from dragonflow.db import api_nb
from dragonflow.db import db_store
from dragonflow.db.drivers import ovsdb_vswitch_impl


df_ryu_opts = [
    cfg.IPOpt('of_listen_address', default='127.0.0.1',
              help=_("Address to listen on for OpenFlow connections.")),
    cfg.PortOpt('of_listen_port', default=ofproto_common.OFP_TCP_PORT,
                help=_("Port to listen on for OpenFlow connections."))
]

config.setup_logging()
LOG = log.getLogger("dragonflow.controller.df_local_controller")

cfg.CONF.register_opts(common_params.df_opts, 'df')
cfg.CONF.register_opts(df_ryu_opts, 'df_ryu')


class DfLocalController(object):

    def __init__(self, chassis_name):
        self.next_network_id = 0
        self.db_store = db_store.DbStore()
        self.chassis_name = chassis_name
        self.ip = cfg.CONF.df.local_ip
        self.tunnel_type = cfg.CONF.df.tunnel_type
        self.sync_finished = False
        nb_driver = df_utils.load_driver(
            cfg.CONF.df.nb_db_class,
            df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        self.nb_api = api_nb.NbApi(
            nb_driver,
            use_pubsub=cfg.CONF.df.enable_df_pub_sub)
        self.vswitch_api = ovsdb_vswitch_impl.OvsdbSwitchApi(self.ip)
        kwargs = dict(
            nb_api=self.nb_api,
            vswitch_api=self.vswitch_api,
            db_store=self.db_store
        )
        app_mgr = app_manager.AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(ryu_base_app.RyuDFAdapter,
                                                 **kwargs)

        self.topology = None
        self.enable_selective_topo_dist = \
            cfg.CONF.df.enable_selective_topology_distribution
        self.remote_chassis_lport_map = {}
        self.integration_bridge = cfg.CONF.df.integration_bridge

    def run(self):
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)
        self.vswitch_api.initialize(self.nb_api)
        self.topology = topology.Topology(self,
                                          self.enable_selective_topo_dist)

        self.vswitch_api.sync()
        # both set_controller and del_controller will delete flows.
        # for reliability, here we should check if controller is set for OVS,
        # if yes, don't set controller and don't delete controller.
        # if no, set controller
        targets = ('tcp:' + cfg.CONF.df_ryu.of_listen_address + ':' +
            str(cfg.CONF.df_ryu.of_listen_port))
        is_controller_set = self.vswitch_api.check_controller(targets)
        if not is_controller_set:
            self.vswitch_api.set_controller(self.integration_bridge, [targets])
        is_fail_mode_set = self.vswitch_api.check_controller_fail_mode(
            'secure')
        if not is_fail_mode_set:
            self.vswitch_api.set_controller_fail_mode(
                self.integration_bridge, 'secure')
        self.open_flow_app.start()
        self.db_sync_loop()

    def db_sync_loop(self):
        while True:
            time.sleep(1)
            self.run_db_poll()
            if self.sync_finished and (
                    self.nb_api.support_publish_subscribe()):
                self.nb_api.register_notification_callback(self)

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

            self.register_chassis()

            self.create_tunnels()

            if not self.enable_selective_topo_dist:

                self.read_switches()

                self.read_security_groups()

                self.port_mappings()

                self.read_routers()

                self.read_floatingip()

            self.sync_finished = True

        except Exception as e:
            self.sync_finished = False
            LOG.warning(_LW("run_db_poll - suppressing exception"))
            LOG.exception(e)

    def chassis_created(self, chassis):
        # Check if tunnel already exists to this chassis
        t_ports = self.vswitch_api.get_tunnel_ports()
        remote_chassis_name = chassis.get_id()
        if self.chassis_name == remote_chassis_name:
            return
        for t_port in t_ports:
            if t_port.get_chassis_id() == remote_chassis_name:
                LOG.info(_LI("remote Chassis Tunnel already installed  = %s") %
                     chassis.__str__())
                return
        # Create tunnel port to this chassis
        LOG.info(_LI("Adding tunnel to remote chassis = %s") %
                 chassis.__str__())
        self.vswitch_api.add_tunnel_port(chassis)

    def chassis_deleted(self, chassis_id):
        LOG.info(_LI("Deleting tunnel to remote chassis = %s") % chassis_id)
        tunnel_ports = self.vswitch_api.get_tunnel_ports()
        for port in tunnel_ports:
            if port.get_chassis_id() == chassis_id:
                self.vswitch_api.delete_port(port)
                return

    def read_switches(self):
        lswitches_to_remove = self.db_store.get_lswitch_keys()
        for lswitch in self.nb_api.get_all_logical_switches():
            self.logical_switch_updated(lswitch)
            if lswitch.get_id() in lswitches_to_remove:
                lswitches_to_remove.remove(lswitch.get_id())

        for lswitch_to_remove in lswitches_to_remove:
            self.logical_switch_deleted(lswitch_to_remove)

    def logical_switch_updated(self, lswitch):
        old_lswitch = self.db_store.get_lswitch(lswitch.get_id())
        if old_lswitch == lswitch:
            return
        #Make sure we have a local network_id mapped before we dispatch
        network_id = self.get_network_id(
            lswitch.get_id(),
        )
        lswitch_conf = {'network_id': network_id, 'lswitch':
            lswitch.__str__()}
        LOG.info(_LI("Adding/Updating Logical Switch = %s") % lswitch_conf)
        self.db_store.set_lswitch(lswitch.get_id(), lswitch)
        self.open_flow_app.notify_update_logical_switch(lswitch)

    def logical_switch_deleted(self, lswitch_id):
        lswitch = self.db_store.get_lswitch(lswitch_id)
        LOG.info(_LI("Removing Logical Switch = %s") % lswitch_id)
        if lswitch is None:
            LOG.warning(_LW("Try to delete a nonexistent lswitch(%s)") %
                        lswitch_id)
            return
        self.open_flow_app.notify_remove_logical_switch(lswitch)
        self.db_store.del_lswitch(lswitch_id)
        self.db_store.del_network_id(lswitch_id)

    def _is_physical_chassis(self, chassis):
        if not chassis or chassis == constants.DRAGONFLOW_VIRTUAL_PORT:
            return False
        return True

    def _logical_port_process(self, lport, original_lport=None):
        chassis = lport.get_chassis()
        local_network_id = self.get_network_id(
            lport.get_lswitch_id(),
        )
        lswitch = self.db_store.get_lswitch(lport.get_lswitch_id())
        if lswitch is not None:
            network_type = lswitch.get_network_type()
            segment_id = lswitch.get_segment_id()

            lport.set_external_value('network_type', network_type)
            if segment_id is not None:
                lport.set_external_value('segmentation_id',
                                     int(segment_id))
        lport.set_external_value('local_network_id', local_network_id)

        if chassis == self.chassis_name:
            lport.set_external_value('is_local', True)
            ofport = self.vswitch_api.get_port_ofport_by_id(lport.get_id())
            if ofport:
                lport.set_external_value('ofport', ofport)
                self.db_store.set_port(lport.get_id(), lport, True)
                if original_lport is None:
                    LOG.info(_LI("Adding new local logical port = %s") %
                             str(lport))
                    self.open_flow_app.notify_add_local_port(lport)
                else:
                    LOG.info(_LI("Updating local logical port = %(port)s, "
                                 "original port = %(original_port)s") %
                             {'port': str(lport),
                              'original_port': str(original_lport)})
                    self.open_flow_app.notify_update_local_port(lport,
                                                                original_lport)
            else:
                LOG.info(_LI("Local logical port %s was not created yet") %
                         str(lport))
        else:
            lport.set_external_value('is_local', False)
            ofport = self.vswitch_api.get_chassis_ofport(chassis)
            if ofport:
                lport.set_external_value('ofport', ofport)
                self.db_store.set_port(lport.get_id(), lport, False)
                if original_lport is None:
                    LOG.info(_LI("Adding new remote logical port = %s") %
                             str(lport))
                    self.open_flow_app.notify_add_remote_port(lport)
                else:
                    LOG.info(_LI("Updating remote logical port = %(port)s, "
                                 "original port = %(original_port)s") %
                             {'port': str(lport),
                              'original_port': str(original_lport)})
                    self.open_flow_app.notify_update_remote_port(
                        lport, original_lport)
            else:
                # TODO(gampel) add handling for this use case
                # remote port but no tunnel to remote Host
                # if this should never happen raise an exception
                LOG.warning(_LW("No tunnel for remote logical port %s") %
                            str(lport))

    def _add_remote_port_on_chassis(self, lport):
        chassis = lport.get_chassis()
        chassis_lports = self.remote_chassis_lport_map.get(chassis)
        if not chassis_lports:
            chassis_value = {'id': chassis, 'ip': chassis,
                             'tunnel_type': self.tunnel_type}
            chassis_inst = api_nb.Chassis(jsonutils.dumps(chassis_value))
            self.chassis_created(chassis_inst)
            self.remote_chassis_lport_map[chassis] = {lport.get_id()}
        else:
            chassis_lports.add(lport.get_id())

    def _delete_remote_port_from_chassis(self, lport):
        chassis = lport.get_chassis()
        chassis_lports = self.remote_chassis_lport_map.get(chassis)
        if chassis_lports is None:
            return
        chassis_lports.remove(lport.get_id())
        if len(chassis_lports) == 0:
            self.chassis_deleted(chassis)
            del self.remote_chassis_lport_map[chassis]

    def logical_port_created(self, lport):
        chassis = lport.get_chassis()
        if not self._is_physical_chassis(chassis):
            LOG.debug(("Port %s has not been bound or it is a vPort") %
                      lport.get_id())
            return
        if lport.get_remote_vtep():
            self._add_remote_port_on_chassis(lport)
        self._logical_port_process(lport)

    def logical_port_updated(self, lport):
        chassis = lport.get_chassis()
        if not self._is_physical_chassis(chassis):
            LOG.debug(("Port %s has not been bound or it is a vPort") %
                      lport.get_id())
            return
        original_lport = self.db_store.get_port(lport.get_id())
        if not original_lport:
            if lport.get_remote_vtep():
                self._add_remote_port_on_chassis(lport)
        else:
            original_chassis = original_lport.get_chassis()
            if original_chassis != chassis:
                if original_lport.get_remote_vtep():
                    self._delete_remote_port_from_chassis(original_lport)

                if lport.get_remote_vtep():
                    self._add_remote_port_on_chassis(lport)
        self._logical_port_process(lport, original_lport)

    def logical_port_deleted(self, lport_id):
        lport = self.db_store.get_port(lport_id)
        if lport is None:
            return
        if lport.get_external_value('is_local'):
            LOG.info(_LI("Removing local logical port = %s") %
                     str(lport))
            if lport.get_external_value('ofport') is not None:
                self.open_flow_app.notify_remove_local_port(lport)
            self.db_store.delete_port(lport.get_id(), True)
        else:
            LOG.info(_LI("Removing remote logical port = %s") %
                     str(lport))
            if lport.get_external_value('ofport') is not None:
                self.open_flow_app.notify_remove_remote_port(lport)
            self.db_store.delete_port(lport.get_id(), False)

        if lport.get_remote_vtep():
            self._delete_remote_port_from_chassis(lport)

    def bridge_port_updated(self, lport):
        self.open_flow_app.notify_update_bridge_port(lport)

    def router_updated(self, lrouter):
        old_lrouter = self.db_store.get_router(lrouter.get_id())
        if old_lrouter is None:
            LOG.info(_LI("Logical Router created = %s") %
                     lrouter.__str__())
            self._add_new_lrouter(lrouter)
            return
        self._update_router_interfaces(old_lrouter, lrouter)
        self._update_router_attributes(old_lrouter, lrouter)
        self.db_store.update_router(lrouter.get_id(), lrouter)

    def router_deleted(self, lrouter_id):
        old_lrouter = self.db_store.get_router(lrouter_id)
        if old_lrouter is None:
            return
        old_router_ports = old_lrouter.get_ports()
        for old_port in old_router_ports:
            self._delete_router_port(old_port)
        self.db_store.delete_router(lrouter_id)

    def security_group_updated(self, secgroup):
        old_secgroup = self.db_store.get_security_group(secgroup.get_id())
        if old_secgroup is None:
            LOG.info(_LI("Security Group created = %s") %
                     secgroup)
            self._add_new_security_group(secgroup)
            return
        self._update_security_group_rules(old_secgroup, secgroup)
        self.db_store.update_security_group(secgroup.get_id(), secgroup)

    def security_group_deleted(self, secgroup_id):
        old_secgroup = self.db_store.get_security_group(secgroup_id)
        if old_secgroup is None:
            return
        self._delete_old_security_group(old_secgroup)

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
            if chassis.get_id() in tunnel_ports:
                del tunnel_ports[chassis.get_id()]
            elif chassis.get_id() == self.chassis_name:
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
            self.db_store.set_network_id(
                logical_dp_id,
                self.next_network_id,
            )
            return self.next_network_id

    def read_routers(self):
        routers_to_remove = self.db_store.get_router_keys()
        for lrouter in self.nb_api.get_routers():
            self.router_updated(lrouter)
            if lrouter.get_id() in routers_to_remove:
                routers_to_remove.remove(lrouter.get_id())

        for router_to_remove in routers_to_remove:
            self.router_deleted(router_to_remove)

    def _update_router_attributes(self, old_router, new_router):
        old_routes = old_router.get_routes()
        new_routes = new_router.get_routes()
        for new_route in new_routes:
            if new_route not in old_routes:
                self._add_router_route(new_router, new_route)
            else:
                old_routes.remove(new_route)
        for old_route in old_routes:
            self._delete_router_route(new_router, old_route)

    def _add_router_route(self, router, route):
        LOG.info(_LI("Adding new logical router route = %s"), route)
        self.open_flow_app.notify_add_router_route(
            router, route)

    def _delete_router_route(self, router, route):
        LOG.info(_LI("Removing logical router route = %s"), route)
        self.open_flow_app.notify_remove_router_route(
            router, route)

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
        LOG.info(_LI("Adding new logical router interface = %s") %
                 router_port.__str__())
        local_network_id = self.db_store.get_network_id(
            router_port.get_lswitch_id()
        )
        self.open_flow_app.notify_add_router_port(
                router, router_port, local_network_id)

    def _delete_router_port(self, router_port):
        LOG.info(_LI("Removing logical router interface = %s") %
                 router_port.__str__())
        local_network_id = self.db_store.get_network_id(
            router_port.get_lswitch_id()
        )
        self.open_flow_app.notify_remove_router_port(
                router_port, local_network_id)

    def _add_new_lrouter(self, lrouter):
        for new_port in lrouter.get_ports():
            self._add_new_router_port(lrouter, new_port)
        routes = lrouter.get_routes()
        for route in routes:
            self._add_router_route(lrouter, route)
        self.db_store.update_router(lrouter.get_id(), lrouter)

    def read_security_groups(self):
        secgroups_to_remove = self.db_store.get_security_group_keys()

        for secgroup in self.nb_api.get_security_groups():
            self.security_group_updated(secgroup)
            if secgroup.get_id() in secgroups_to_remove:
                secgroups_to_remove.remove(secgroup.get_id())

        for secgroup_to_remove in secgroups_to_remove:
            self.security_group_deleted(secgroup_to_remove)

    def _update_security_group_rules(self, old_secgroup, new_secgroup):
        new_secgroup_rules = new_secgroup.get_rules()
        old_secgroup_rules = old_secgroup.get_rules()
        for new_rule in new_secgroup_rules:
            if new_rule not in old_secgroup_rules:
                self._add_new_security_group_rule(new_secgroup, new_rule)
            else:
                old_secgroup_rules.remove(new_rule)

        for old_rule in old_secgroup_rules:
            self._delete_security_group_rule(old_secgroup, old_rule)

    def _add_new_security_group(self, secgroup):
        for new_rule in secgroup.get_rules():
            self._add_new_security_group_rule(secgroup, new_rule)
        self.db_store.update_security_group(secgroup.get_id(), secgroup)

    def _delete_old_security_group(self, secgroup):
        for rule in secgroup.get_rules():
            self._delete_security_group_rule(secgroup, rule)
        self.db_store.delete_security_group(secgroup.get_id())

    def _add_new_security_group_rule(self, secgroup, secgroup_rule):
        LOG.info(_LI("Adding new secgroup rule = %s") %
                 secgroup_rule)
        self.open_flow_app.notify_add_security_group_rule(
                 secgroup, secgroup_rule)

    def _delete_security_group_rule(self, secgroup, secgroup_rule):
        LOG.info(_LI("Removing secgroup rule = %s") %
                 secgroup_rule)
        self.open_flow_app.notify_remove_security_group_rule(
                 secgroup, secgroup_rule)

    def read_floatingip(self):
        fips_to_remove = self.db_store.get_floatingip_keys()
        for floatingip in self.nb_api.get_floatingips():
            self.floatingip_updated(floatingip)
            if floatingip.get_id() in fips_to_remove:
                fips_to_remove.remove(floatingip.get_id())

        for fip_to_remove in fips_to_remove:
            self.floatingip_deleted(fip_to_remove)

    def floatingip_updated(self, floatingip):
        # check whether this floatingip is associated with a lport or not
        if floatingip.get_lport_id():
            if self.db_store.get_local_port(floatingip.get_lport_id()) is None:
                return

        old_floatingip = self.db_store.get_floatingip(floatingip.get_id())
        if old_floatingip is None:
            # The new floatingip should be associated with a lport
            if not floatingip.get_lport_id():
                return
            self._associate_floatingip(floatingip)
            return
        self._update_floatingip(old_floatingip, floatingip)

    def floatingip_deleted(self, floatingip_id):
        floatingip = self.db_store.get_floatingip(floatingip_id)
        if not floatingip:
            return
        self.open_flow_app.notify_delete_floatingip(floatingip)
        LOG.info(_LI("Floatingip is deleted. Floatingip = %s") %
                 str(floatingip))

    def publisher_updated(self, publisher):
        self.db_store.update_publisher(publisher.get_id(), publisher)
        LOG.info(_LI('Registering to new publisher: %s'), str(publisher))
        self.nb_api.subscriber.register_listen_address(publisher.get_uri())

    def publisher_deleted(self, uuid):
        publisher = self.db_store.get_publisher(uuid)
        if publisher:
            LOG.info(_LI('Deleting publisher: %s'), str(publisher))
            self.nb_api.subscriber.unregister_listen_address(
                publisher.get_uri()
            )
            self.db_store.delete_publisher(uuid)

    def _associate_floatingip(self, floatingip):
        self.db_store.update_floatingip(floatingip.get_id(), floatingip)
        self.open_flow_app.notify_associate_floatingip(floatingip)
        LOG.info(_LI("Floatingip is associated with port. Floatingip = %s") %
                 str(floatingip))

    def _disassociate_floatingip(self, floatingip):
        self.db_store.delete_floatingip(floatingip.get_id())
        self.open_flow_app.notify_disassociate_floatingip(floatingip)
        LOG.info(_LI("Floatingip is disassociated from port."
                 " Floatingip = %s") % str(floatingip))

    def _update_floatingip(self, old_floatingip, new_floatingip):
        if new_floatingip.get_lport_id() != old_floatingip.get_lport_id():
            self._disassociate_floatingip(old_floatingip)
            if new_floatingip.get_lport_id():
                self._associate_floatingip(new_floatingip)

    def ovs_port_updated(self, ovs_port):
        self.open_flow_app.notify_ovs_port_updated(ovs_port)
        self.topology.ovs_port_updated(ovs_port)

    def ovs_port_deleted(self, ovs_port):
        self.open_flow_app.notify_ovs_port_deleted(ovs_port)
        self.topology.ovs_port_deleted(ovs_port.get_id())

    def ovs_sync_finished(self):
        self.open_flow_app.notify_ovs_sync_finished()

    def ovs_sync_started(self):
        self.open_flow_app.notify_ovs_sync_started()

    def get_nb_api(self):
        return self.nb_api

    def get_db_store(self):
        return self.db_store

    def get_openflow_app(self):
        return self.open_flow_app

    def get_chassis_name(self):
        return self.chassis_name


def init_ryu_config():
    ryu_cfg.CONF(project='ryu', args=[])
    ryu_cfg.CONF.ofp_listen_host = cfg.CONF.df_ryu.of_listen_address
    ryu_cfg.CONF.ofp_tcp_listen_port = cfg.CONF.df_ryu.of_listen_port


# Run this application like this:
# python df_local_controller.py <chassis_unique_name>
# <local ip address> <southbound_db_ip_address>
def main():
    chassis_name = socket.gethostname()
    common_config.init(sys.argv[1:])
    init_ryu_config()
    controller = DfLocalController(chassis_name)
    controller.run()
