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
from oslo_log import log
from ryu.base import app_manager
from ryu import cfg as ryu_cfg

from dragonflow._i18n import _LI, _LW
from dragonflow.common import constants
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller import df_db_objects_refresh
from dragonflow.controller import ryu_base_app
from dragonflow.controller import topology
from dragonflow.db import api_nb
from dragonflow.db import db_consistent
from dragonflow.db import db_store
from dragonflow.ovsdb import vswitch_impl


LOG = log.getLogger("dragonflow.controller.df_local_controller")


class DfLocalController(object):

    def __init__(self, chassis_name):
        self.db_store = db_store.DbStore()
        self.chassis_name = chassis_name
        self.mgt_ip = cfg.CONF.df.management_ip
        self.ip = cfg.CONF.df.local_ip
        if cfg.CONF.df.tunnel_types:
            # Virtual tunnel port support multiple tunnel types together
            self.tunnel_types = cfg.CONF.df.tunnel_types
        else:
            # NOTE(xiaohhui): This should be removed along with the config
            # option tunnel_type
            self.tunnel_types = [cfg.CONF.df.tunnel_type]
        self.sync_finished = False
        self.port_status_notifier = None
        nb_driver = df_utils.load_driver(
            cfg.CONF.df.nb_db_class,
            df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        self.nb_api = api_nb.NbApi(
            nb_driver,
            use_pubsub=cfg.CONF.df.enable_df_pub_sub)
        self.vswitch_api = vswitch_impl.OvsApi(self.mgt_ip)
        if cfg.CONF.df.enable_port_status_notifier:
            self.port_status_notifier = df_utils.load_driver(
                     cfg.CONF.df.port_status_notifier,
                     df_utils.DF_PORT_STATUS_DRIVER_NAMESPACE)
        kwargs = dict(
            nb_api=self.nb_api,
            vswitch_api=self.vswitch_api,
            db_store=self.db_store
        )
        app_mgr = app_manager.AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(ryu_base_app.RyuDFAdapter,
                                                 **kwargs)
        self.topology = None
        self.db_consistency_manager = None
        self.enable_db_consistency = cfg.CONF.df.enable_df_db_consistency
        self.enable_selective_topo_dist = \
            cfg.CONF.df.enable_selective_topology_distribution
        self.integration_bridge = cfg.CONF.df.integration_bridge

    def run(self):
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)
        self.vswitch_api.initialize(self.nb_api)
        if cfg.CONF.df.enable_port_status_notifier:
            self.port_status_notifier.initialize(mech_driver=None,
                                             nb_api=self.nb_api,
                                             pub=self.nb_api.publisher,
                                             sub=None,
                                             is_neutron_server=False)
        self.topology = topology.Topology(self,
                                          self.enable_selective_topo_dist)
        if self.enable_db_consistency:
            self.db_consistency_manager = \
                db_consistent.DBConsistencyManager(self)
            self.nb_api.set_db_consistency_manager(self.db_consistency_manager)
            self.db_consistency_manager.daemonize()

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
        self.create_tunnels()
        df_db_objects_refresh.initialize_object_refreshers(self)
        self.db_sync_loop()

    def db_sync_loop(self):
        while True:
            time.sleep(1)
            self.run_db_poll()
            if self.sync_finished and (
                    self.nb_api.support_publish_subscribe()):
                self.nb_api.register_notification_callback(self)

    def run_sync(self, mode=None):
        if mode == 'full_sync':
            # For a full sync, df needs to clean the local cache, so that
            # all resources will be treated as new resource, and thus be
            # applied to local.
            self.db_store.clear()
        while True:
            time.sleep(1)
            self.run_db_poll()
            if self.sync_finished:
                return

    def run_db_poll(self):
        try:
            self.register_chassis()

            topics = self.topology.get_subscribed_topics()
            df_db_objects_refresh.sync_local_cache_from_nb_db(topics)
            self.sync_finished = True
        except Exception as e:
            self.sync_finished = False
            LOG.warning(_LW("run_db_poll - suppressing exception"))
            LOG.exception(e)

    def update_chassis(self, chassis):
        self.db_store.update_chassis(chassis.get_id(), chassis)
        remote_chassis_name = chassis.get_id()
        if self.chassis_name == remote_chassis_name:
            return

        # Notify about remote port update
        remote_ports = self.db_store.get_ports_by_chassis(remote_chassis_name)
        for port in remote_ports:
            self._logical_port_process(port, None)

    def delete_chassis(self, chassis_id):
        LOG.info(_LI("Deleting remote ports in remote chassis %s"), chassis_id)
        # Chassis is deleted, there is no reason to keep the remote port
        # in it.
        remote_ports = self.db_store.get_ports_by_chassis(chassis_id)
        for port in remote_ports:
            self.logical_port_deleted(port.get_id())
        self.db_store.delete_chassis(chassis_id)

    def update_lswitch(self, lswitch):
        old_lswitch = self.db_store.get_lswitch(lswitch.get_id())
        if not df_utils.is_valid_version(
                old_lswitch.inner_obj if old_lswitch else None,
                lswitch.inner_obj):
            return

        LOG.info(_LI("Adding/Updating Logical Switch = %s"), lswitch)
        self.db_store.set_lswitch(lswitch.get_id(), lswitch)
        self.open_flow_app.notify_update_logical_switch(lswitch)

    def delete_lswitch(self, lswitch_id):
        lswitch = self.db_store.get_lswitch(lswitch_id)
        LOG.info(_LI("Removing Logical Switch = %s") % lswitch_id)
        if lswitch is None:
            LOG.warning(_LW("Try to delete a nonexistent lswitch(%s)") %
                        lswitch_id)
            return
        self.open_flow_app.notify_remove_logical_switch(lswitch)
        self.db_store.del_lswitch(lswitch_id)

    def _notify_active_ports_updated_when_lport_created(self, lport):
        active_ports = self.nb_api.get_active_ports(lport.get_topic())
        for active_port in active_ports:
            if active_port.get_detected_lport_id() == lport.get_id():
                self.db_store.update_active_port(active_port.get_id(),
                                                 active_port)
                self.open_flow_app.notify_update_active_port(active_port,
                                                             None)

    def _notify_active_ports_updated_when_lport_removed(self, lport):
        active_ports = self.db_store.get_active_ports(lport.get_topic())
        for active_port in active_ports:
            if active_port.get_detected_lport_id() == lport.get_id():
                self.open_flow_app.notify_remove_active_port(active_port)
                self.db_store.delete_active_port(active_port.get_id())

    def _is_physical_chassis(self, chassis):
        if not chassis or chassis == constants.DRAGONFLOW_VIRTUAL_PORT:
            return False
        return True

    def _logical_port_process(self, lport, original_lport=None):
        lswitch = self.db_store.get_lswitch(lport.get_lswitch_id())
        if not lswitch:
            LOG.warning(_LW("Could not find lswitch for lport: %s"),
                        lport.get_id())
            return
        lport.set_external_value('local_network_id',
                                 lswitch.get_unique_key())
        network_type = lswitch.get_network_type()
        segment_id = lswitch.get_segment_id()
        physical_network = lswitch.get_physical_network()

        lport.set_external_value('network_type', network_type)
        if segment_id is not None:
            lport.set_external_value('segmentation_id',
                                     int(segment_id))
        if physical_network:
            lport.set_external_value('physical_network', physical_network)

        chassis = lport.get_chassis()
        if chassis == self.chassis_name:
            lport.set_external_value('is_local', True)
            self.db_store.set_port(lport.get_id(), lport, True)
            ofport = self.vswitch_api.get_port_ofport_by_id(lport.get_id())
            if ofport:
                lport.set_external_value('ofport', ofport)
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
                return
        else:
            lport.set_external_value('is_local', False)
            self.db_store.set_port(lport.get_id(), lport, False)
            if lport.get_remote_vtep():
                # Remote port that exists in other network pod.
                lport.set_external_value('peer_vtep_address',
                                         lport.get_chassis())
            else:
                # Remote port that exists in current network pod.
                remote_chassis = self.db_store.get_chassis(lport.get_chassis())
                if not remote_chassis:
                    # chassis has not been online yet.
                    return
                lport.set_external_value('peer_vtep_address',
                                         remote_chassis.get_ip())

            ofport = self.vswitch_api.get_vtp_ofport(
                lport.get_external_value('network_type'))
            if ofport:
                lport.set_external_value('ofport', ofport)
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
                # The tunnel port online event will update the remote logical
                # port. Log this warning first.
                LOG.warning(_LW("No tunnel for remote logical port %s"),
                            lport)
                return

        if original_lport is None:
            self._notify_active_ports_updated_when_lport_created(lport)

    def update_lport(self, lport):
        chassis = lport.get_chassis()
        if not self._is_physical_chassis(chassis):
            LOG.debug(("Port %s has not been bound or it is a vPort") %
                      lport.get_id())
            return
        original_lport = self.db_store.get_port(lport.get_id())
        if original_lport and not original_lport.get_external_value("ofport"):
            original_lport = None

        if not df_utils.is_valid_version(
                original_lport.inner_obj if original_lport else None,
                lport.inner_obj):
            return
        self._logical_port_process(lport, original_lport)

    def delete_lport(self, lport_id):
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

        self._notify_active_ports_updated_when_lport_removed(lport)

    def bridge_port_updated(self, lport):
        self.open_flow_app.notify_update_bridge_port(lport)

    def update_lrouter(self, lrouter):
        old_lrouter = self.db_store.get_router(lrouter.get_id())
        if not df_utils.is_valid_version(
                old_lrouter.inner_obj if old_lrouter else None,
                lrouter.inner_obj):
            return
        self.open_flow_app.notify_update_router(lrouter, old_lrouter)
        self.db_store.update_router(lrouter.get_id(), lrouter)

    def delete_lrouter(self, lrouter_id):
        router = self.db_store.get_router(lrouter_id)
        if router is None:
            LOG.warning(_LW("Try to delete a nonexistent router(%s)"),
                        lrouter_id)
            return
        LOG.info(_LI("Removing router = %s"), lrouter_id)
        self.open_flow_app.notify_delete_router(router)
        self.db_store.delete_router(lrouter_id)

    def update_secgroup(self, secgroup):
        old_secgroup = self.db_store.get_security_group(secgroup.get_id())
        if old_secgroup is None:
            LOG.info(_LI("Security Group created = %s") %
                     secgroup)
            self._add_new_security_group(secgroup)
            return
        if not df_utils.is_valid_version(
                old_secgroup.inner_obj if old_secgroup else None,
                secgroup.inner_obj):
            return
        self._update_security_group_rules(old_secgroup, secgroup)
        self.db_store.update_security_group(secgroup.get_id(), secgroup)

    def delete_secgroup(self, secgroup_id):
        old_secgroup = self.db_store.get_security_group(secgroup_id)
        if old_secgroup is None:
            return
        self._delete_old_security_group(old_secgroup)

    def update_qospolicy(self, qos):
        original_qos = self.db_store.get_qos_policy(qos.get_id())
        if not df_utils.is_valid_version(
                original_qos.inner_obj if original_qos else None,
                qos.inner_obj):
            return

        self.db_store.set_qos_policy(qos.get_id(), qos)
        if not original_qos:
            return

        self.open_flow_app.notify_update_qos_policy(qos)

    def delete_qospolicy(self, qos_id):
        qos = self.db_store.get_qos_policy(qos_id)
        if not qos:
            return

        self.open_flow_app.notify_delete_qos_policy(qos)
        self.db_store.delete_qos_policy(qos_id)

    def register_chassis(self):
        # Get all chassis from nb db to db store.
        for c in self.nb_api.get_all_chassis():
            self.db_store.update_chassis(c.get_id(), c)

        chassis = self.db_store.get_chassis(self.chassis_name)
        if chassis is None:
            self.nb_api.add_chassis(self.chassis_name,
                                    self.ip,
                                    self.tunnel_types)
        else:
            kwargs = {}
            old_tunnel_types = chassis.get_tunnel_types()
            if (not isinstance(old_tunnel_types, list) or
                    set(self.tunnel_types) != set(old_tunnel_types)):
                # There are 2 cases that needs update tunnel type in
                # chassis. 1) User changes tunnel types in conf file
                # 2) An old controller support only one type tunnel switch
                # to support virtual tunnel port.
                kwargs['tunnel_types'] = self.tunnel_types
            if self.ip != chassis.get_ip():
                kwargs['ip'] = self.ip

            if kwargs:
                self.nb_api.update_chassis(self.chassis_name, **kwargs)

    def create_tunnels(self):
        tunnel_ports = self.vswitch_api.get_virtual_tunnel_ports()
        for tunnel_port in tunnel_ports:
            if tunnel_port.get_tunnel_type() not in self.tunnel_types:
                self.vswitch_api.delete_port(tunnel_port)

        for t in self.tunnel_types:
            # The customized ovs idl will ingore the command if the port
            # already exists.
            self.vswitch_api.add_virtual_tunnel_port(t)

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

    def update_floatingip(self, floatingip):
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
        if not df_utils.is_valid_version(
                old_floatingip.inner_obj if old_floatingip else None,
                floatingip.inner_obj):
            return
        self._update_floatingip(old_floatingip, floatingip)

    def delete_floatingip(self, floatingip_id):
        floatingip = self.db_store.get_floatingip(floatingip_id)
        if not floatingip:
            return
        self.open_flow_app.notify_delete_floatingip(floatingip)
        LOG.info(_LI("Floatingip is deleted. Floatingip = %s") %
                 str(floatingip))
        self.db_store.delete_floatingip(floatingip_id)

    def update_publisher(self, publisher):
        self.db_store.update_publisher(publisher.get_id(), publisher)
        LOG.info(_LI('Registering to new publisher: %s'), str(publisher))
        self.nb_api.subscriber.register_listen_address(publisher.get_uri())

    def delete_publisher(self, uuid):
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

    def update_activeport(self, active_port):
        old_active_port = self.db_store.get_active_port(active_port.get_id())
        lport_id = active_port.get_detected_lport_id()
        lport = self.db_store.get_local_port(lport_id,
                                             active_port.get_topic())
        LOG.info(_LI("Active port updated. Active port = %(new)s, "
                     "old active port = %(old)s"),
                 {'new': active_port, 'old': old_active_port})
        if lport is not None:
            self.db_store.update_active_port(active_port.get_id(),
                                             active_port)
            self.open_flow_app.notify_update_active_port(active_port,
                                                         old_active_port)
        else:
            LOG.info(_LI("The logical port is not ready for the "
                         "active node: %s"), active_port)

    def delete_activeport(self, active_port_key):
        active_port = self.db_store.get_active_port(active_port_key)
        if active_port is not None:
            self.db_store.delete_active_port(active_port_key)
            LOG.info(_LI("Active node was removed. Active node = %s"),
                     active_port)
            lport_id = active_port.get_detected_lport_id()
            lport = self.db_store.get_local_port(lport_id,
                                                 active_port.get_topic())
            if lport is not None:
                self.open_flow_app.notify_remove_active_port(active_port)

    def get_nb_api(self):
        return self.nb_api

    def get_portstatus_notifier(self):
        return self.port_status_notifier

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
    config.setup_logging()
    init_ryu_config()
    controller = DfLocalController(chassis_name)
    controller.run()
