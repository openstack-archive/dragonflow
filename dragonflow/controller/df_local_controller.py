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

import functools
import sys
import time

from neutron.common import config as common_config
from oslo_log import log
from ryu.base import app_manager
from ryu import cfg as ryu_cfg

from dragonflow.common import constants
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller import df_db_objects_refresh
from dragonflow.controller import ryu_base_app
from dragonflow.controller import topology
from dragonflow.db import api_nb
from dragonflow.db import db_consistent
from dragonflow.db import db_store
from dragonflow.db import db_store2
from dragonflow.db import model_framework
from dragonflow.db import model_proxy
from dragonflow.db import models
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.db.models import mixins
from dragonflow.ovsdb import vswitch_impl


LOG = log.getLogger(__name__)


class DfLocalController(object):

    def __init__(self, chassis_name):
        self.db_store = db_store.DbStore()
        self.db_store2 = db_store2.get_instance()

        self.chassis_name = chassis_name
        self.ip = cfg.CONF.df.local_ip
        # Virtual tunnel port support multiple tunnel types together
        self.tunnel_types = cfg.CONF.df.tunnel_types
        self.sync_finished = False
        self.nb_api = api_nb.NbApi.get_instance(False)
        self.vswitch_api = vswitch_impl.OvsApi(cfg.CONF.df.management_ip)

        self.neutron_notifier = None
        if cfg.CONF.df.enable_neutron_notifier:
            self.neutron_notifier = df_utils.load_driver(
                     cfg.CONF.df.neutron_notifier,
                     df_utils.DF_NEUTRON_NOTIFIER_DRIVER_NAMESPACE)

        app_mgr = app_manager.AppManager.get_instance()
        self.open_flow_app = app_mgr.instantiate(
            ryu_base_app.RyuDFAdapter,
            nb_api=self.nb_api,
            vswitch_api=self.vswitch_api,
            db_store=self.db_store,
            neutron_server_notifier=self.neutron_notifier,
        )
        self.topology = None
        self.db_consistency_manager = None
        self.enable_db_consistency = cfg.CONF.df.enable_df_db_consistency
        self.enable_selective_topo_dist = \
            cfg.CONF.df.enable_selective_topology_distribution

    def run(self):
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)
        self.vswitch_api.initialize(self.nb_api)
        if cfg.CONF.df.enable_neutron_notifier:
            self.neutron_notifier.initialize(nb_api=self.nb_api,
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
        integration_bridge = cfg.CONF.df.integration_bridge
        if not is_controller_set:
            self.vswitch_api.set_controller(integration_bridge, [targets])
        is_fail_mode_set = self.vswitch_api.check_controller_fail_mode(
            'secure')
        if not is_fail_mode_set:
            self.vswitch_api.set_controller_fail_mode(
                integration_bridge, 'secure')
        self.open_flow_app.start()
        self.create_tunnels()
        self._register_models()
        self.db_sync_loop()

    def _register_legacy_model_refreshers(self):
        refreshers = [
            df_db_objects_refresh.DfObjectRefresher(
                'Ports',
                self.db_store.get_port_keys,
                self.nb_api.get_all_logical_ports,
                self.update_lport,
                self.delete_lport,
            ),
            df_db_objects_refresh.DfObjectRefresher(
                'Floating IPs',
                self.db_store.get_floatingip_keys,
                self.nb_api.get_floatingips,
                self.update_floatingip,
                self.delete_floatingip,
            ),
            df_db_objects_refresh.DfObjectRefresher(
                'Active Ports',
                self.db_store.get_active_port_keys,
                self.nb_api.get_active_ports,
                self.update_activeport,
                self.delete_activeport,
            ),
        ]

        for refresher in refreshers:
            df_db_objects_refresh.add_refresher(refresher)

    def _register_legacy_model_consistency_handlers(self):
        if not self.enable_db_consistency:
            return

        handlers = [
            db_consistent.ModelHandler(
                models.LogicalPort,
                self.db_store.get_ports,
                self.nb_api.get_all_logical_ports,
                self.update,
                self.delete_by_id,
            ),
            db_consistent.ModelHandler(
                models.Floatingip,
                self.db_store.get_floatingips,
                self.nb_api.get_floatingips,
                self.update,
                self.delete_by_id,
            ),
        ]

        for handler in handlers:
            self.db_consistency_manager.add_handler(handler)

    def _register_models(self):
        for model in model_framework.iter_models_by_dependency_order():
            # FIXME (dimak) do not register topicless models for now
            if issubclass(model, mixins.Topic):
                df_db_objects_refresh.add_refresher(
                    df_db_objects_refresh.DfObjectRefresher(
                        model.__name__,
                        functools.partial(self.db_store2.get_keys_by_topic,
                                          model),
                        functools.partial(self.nb_api.get_all, model),
                        self.update,
                        functools.partial(self.delete_by_id, model),
                    ),
                )

                if (self.enable_db_consistency and
                        issubclass(model, mixins.Version)):
                    # Register only versioned models for now
                    self.db_consistency_manager.add_handler(
                        db_consistent.ModelHandler.create_using_controller(
                            model,
                            self,
                        ),
                    )

        self._register_legacy_model_refreshers()
        self._register_legacy_model_consistency_handlers()

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
            self.db_store2.clear()
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
            LOG.warning("run_db_poll - suppressing exception")
            LOG.exception(e)

    def update_chassis(self, chassis):
        self.db_store2.update(chassis)
        remote_chassis_name = chassis.id
        if self.chassis_name == remote_chassis_name:
            return

        # Notify about remote port update
        remote_ports = self.db_store.get_ports_by_chassis(remote_chassis_name)
        for port in remote_ports:
            self._logical_port_process(port, None)

    def delete_chassis(self, chassis):
        LOG.info("Deleting remote ports in remote chassis %s", chassis.id)
        # Chassis is deleted, there is no reason to keep the remote port
        # in it.
        remote_ports = self.db_store.get_ports_by_chassis(chassis.id)
        for port in remote_ports:
            self.delete_lport(port.get_id())
        self.db_store2.delete(chassis)

    def _notify_active_ports_updated_when_lport_created(self, lport):
        active_ports = self.db_store.get_active_ports(lport.get_topic())
        for active_port in active_ports:
            if active_port.get_detected_lport_id() == lport.get_id():
                self.open_flow_app.notify_update_active_port(active_port,
                                                             None)

    def _notify_active_ports_updated_when_lport_removed(self, lport):
        active_ports = self.db_store.get_active_ports(lport.get_topic())
        for active_port in active_ports:
            if active_port.get_detected_lport_id() == lport.get_id():
                self.open_flow_app.notify_remove_active_port(active_port)
                self.db_store.delete_active_port(active_port.get_id())

    def _is_physical_chassis(self, chassis):
        if not chassis:
            return False
        if chassis.id == constants.DRAGONFLOW_VIRTUAL_PORT:
            return False
        if model_proxy.is_model_proxy(chassis) and not chassis.get_object():
            return False
        return True

    # update migration flows for VM migration
    def update_migration_flows(self, lport):
        # This method processes the migration event sent from source node.
        # There are three parts for event process, source node, destination
        # node, other nodes which related to topic of migrating VM, according
        # to the chassis ID in lport, and local chassis..
        port_id = lport.get_id()
        migration = self.nb_api.get_lport_migration(port_id)
        original_lport = self.db_store.get_port(port_id)

        if migration:
            dest_chassis = migration['migration']
        else:
            LOG.info("last lport deleted of this topic, do nothing %s",
                     lport)
            return

        if not self._set_lport_external_values(lport):
            return

        if dest_chassis == self.chassis_name:
            # destination node
            ofport = self.vswitch_api.get_port_ofport_by_id(lport.get_id())
            lport.set_external_value('ofport', ofport)
            lport.set_external_value('is_local', True)
            self.db_store.set_port(port_id, lport, True)

            LOG.info("dest process migration event port = %(port)s"
                     "original_port = %(original_port)s"
                     "chassis = %(chassis)s"
                     "self_chassis = %(self_chassis)s",
                     {'port': str(lport),
                      'original_port': str(original_lport),
                      'chassis': dest_chassis,
                      'self_chassis': self.chassis_name})
            if original_lport:
                self.open_flow_app.notify_remove_remote_port(original_lport)
            self.open_flow_app.notify_add_local_port(lport)
            return

        # Here It could be either source node or other nodes, so
        # get ofport from chassis.
        ofport = self.vswitch_api.get_vtp_ofport(
            lport.get_external_value('network_type'))
        lport.set_external_value('ofport', ofport)
        remote_chassis = self.db_store.get_chassis(dest_chassis)
        if not remote_chassis:
            # chassis has not been online yet.
            return
        lport.set_external_value('peer_vtep_address',
                                 remote_chassis.get_ip())

        LOG.info("src process migration event port = %(port)s"
                 "original_port = %(original_port)s"
                 "chassis = %(chassis)s",
                 {'port': str(lport),
                  'original_port': str(original_lport),
                  'chassis': dest_chassis})

        # source node and other related nodes
        if original_lport and lport.get_chassis() != self.chassis_name:
            self.open_flow_app.notify_remove_remote_port(original_lport)

        self.open_flow_app.notify_add_remote_port(lport)

    def _logical_port_process(self, lport, original_lport=None):
        if not self._set_lport_external_values(lport):
            return

        chassis = lport.get_chassis()
        if chassis == self.chassis_name:
            lport.set_external_value('is_local', True)
            self.db_store.set_port(lport.get_id(), lport, True)
            ofport = self.vswitch_api.get_port_ofport_by_id(lport.get_id())
            if ofport:
                lport.set_external_value('ofport', ofport)
                if original_lport is None:
                    LOG.info("Adding new local logical port = %s", lport)
                    self.open_flow_app.notify_add_local_port(lport)
                else:
                    LOG.info("Updating local logical port = %(port)s, "
                             "original port = %(original_port)s",
                             {'port': lport,
                              'original_port': original_lport})
                    if lport.get_chassis() != original_lport.get_chassis():
                        LOG.info("migrating original chassis %(original)s"
                                 "current chassis %(current)s",
                                 {'original':
                                  original_lport.get_chassis(),
                                  'current': lport.get_chassis()})
                        self.nb_api.delete_lport_migration(lport.get_id())
                        return
                    self.open_flow_app.notify_update_local_port(lport,
                                                                original_lport)
            else:
                LOG.info("Local logical port %s was not created yet", lport)
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
                remote_chassis = self.db_store2.get_one(
                    core.Chassis(id=lport.get_chassis()))
                if not remote_chassis:
                    # chassis has not been online yet.
                    return
                lport.set_external_value('peer_vtep_address',
                                         remote_chassis.ip)

            ofport = self.vswitch_api.get_vtp_ofport(
                lport.get_external_value('network_type'))
            if ofport:
                lport.set_external_value('ofport', ofport)
                if original_lport is None:
                    LOG.info("Adding new remote logical port = %s", lport)
                    self.open_flow_app.notify_add_remote_port(lport)
                else:
                    LOG.info("Updating remote logical port = %(port)s, "
                             "original port = %(original_port)s",
                             {'port': lport,
                              'original_port': original_lport})
                    # update chassis
                    if lport.get_chassis() != original_lport.get_chassis():
                        return
                    self.open_flow_app.notify_update_remote_port(
                        lport, original_lport)
            else:
                # The tunnel port online event will update the remote logical
                # port. Log this warning first.
                LOG.warning("No tunnel for remote logical port %s", lport)
                return

        if original_lport is None:
            self._notify_active_ports_updated_when_lport_created(lport)

    def _set_lport_external_values(self, lport):
        lswitch = self.db_store2.get_one(
            l2.LogicalSwitch(id=lport.get_lswitch_id()))
        if not lswitch:
            LOG.warning("Could not find lswitch for lport: %s",
                        lport.get_id())
            return False
        lport.set_external_value('local_network_id',
                                 lswitch.unique_key)
        network_type = lswitch.network_type
        segment_id = lswitch.segmentation_id
        physical_network = lswitch.physical_network

        lport.set_external_value('network_type', network_type)
        if segment_id is not None:
            lport.set_external_value('segmentation_id',
                                     int(segment_id))
        if physical_network:
            lport.set_external_value('physical_network', physical_network)

        return True

    def update_lport(self, lport):
        chassis = model_proxy.create_reference(
                core.Chassis, lport.get_chassis())
        if (not lport.get_remote_vtep() and
                not self._is_physical_chassis(chassis)):
            LOG.debug(("Port %s has not been bound or it is a vPort"),
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
            LOG.info("Removing local logical port = %s", lport)
            if lport.get_external_value('ofport') is not None:
                self.open_flow_app.notify_remove_local_port(lport)
            self.db_store.delete_port(lport.get_id(), True)
        else:
            LOG.info("Removing remote logical port = %s", lport)
            if lport.get_external_value('ofport') is not None:
                self.open_flow_app.notify_remove_remote_port(lport)
            self.db_store.delete_port(lport.get_id(), False)

        self._notify_active_ports_updated_when_lport_removed(lport)

    def register_chassis(self):
        # Get all chassis from nb db to db store.
        for c in self.nb_api.get_all(core.Chassis):
            self.db_store2.update(c)

        old_chassis = self.db_store2.get_one(
            core.Chassis(id=self.chassis_name))

        chassis = core.Chassis(
            id=self.chassis_name,
            ip=self.ip,
            tunnel_types=self.tunnel_types,
        )
        if cfg.CONF.df.external_host_ip:
            chassis.external_host_ip = cfg.CONF.df.external_host_ip

        self.db_store2.update(chassis)

        if old_chassis is None:
            self.nb_api.create(chassis)
        elif old_chassis != chassis:
            self.nb_api.update(chassis)

    def create_tunnels(self):
        tunnel_ports = self.vswitch_api.get_virtual_tunnel_ports()
        for tunnel_port in tunnel_ports:
            if tunnel_port.get_tunnel_type() not in self.tunnel_types:
                self.vswitch_api.delete_port(tunnel_port)

        for t in self.tunnel_types:
            # The customized ovs idl will ingore the command if the port
            # already exists.
            self.vswitch_api.add_virtual_tunnel_port(t)

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
        LOG.info("Floatingip is deleted. Floatingip = %s", floatingip)
        self.db_store.delete_floatingip(floatingip_id)

    def update_publisher(self, publisher):
        self.db_store2.update(publisher)
        LOG.info('Registering to new publisher: %s', str(publisher))
        self.nb_api.subscriber.register_listen_address(publisher.uri)

    def delete_publisher(self, publisher):
        LOG.info('Deleting publisher: %s', str(publisher))
        self.nb_api.subscriber.unregister_listen_address(publisher.uri)
        self.db_store2.delete(publisher)

    def _associate_floatingip(self, floatingip):
        self.db_store.update_floatingip(floatingip.get_id(), floatingip)
        self.open_flow_app.notify_associate_floatingip(floatingip)
        LOG.info("Floatingip is associated with port. Floatingip = %s",
                 floatingip)

    def _disassociate_floatingip(self, floatingip):
        self.db_store.delete_floatingip(floatingip.get_id())
        self.open_flow_app.notify_disassociate_floatingip(floatingip)
        LOG.info("Floatingip is disassociated from port. "
                 "Floatingip = %s", floatingip)

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
        LOG.info("Active port updated. Active port = %(new)s, "
                 "old active port = %(old)s",
                 {'new': active_port, 'old': old_active_port})
        self.db_store.update_active_port(active_port.get_id(),
                                         active_port)
        if lport:
            self.open_flow_app.notify_update_active_port(active_port,
                                                         old_active_port)
        else:
            LOG.info("The logical port is not ready for the "
                     "active node: %s", active_port)

    def delete_activeport(self, active_port_key):
        active_port = self.db_store.get_active_port(active_port_key)
        if active_port is not None:
            self.db_store.delete_active_port(active_port_key)
            LOG.info("Active node was removed. Active node = %s",
                     active_port)
            lport_id = active_port.get_detected_lport_id()
            lport = self.db_store.get_local_port(lport_id,
                                                 active_port.get_topic())
            if lport is not None:
                self.open_flow_app.notify_remove_active_port(active_port)

    def _is_newer(self, obj, cached_obj):
        '''Check wether obj is newer than cached_on.

        If obj is a subtype of Version mixin we can use is_newer_than,
        otherwise we assume that our NB-received object is always newer than
        the cached copy.
        '''
        try:
            return obj.is_newer_than(cached_obj)
        except AttributeError:
            return True

    def update_model_object(self, obj):
        original_obj = self.db_store2.get_one(obj)
        if original_obj is None:
            obj.emit_created()
        elif self._is_newer(obj, original_obj):
            obj.emit_updated(original_obj)
        else:
            return

        self.db_store2.update(obj)

    def delete_model_object(self, obj):
        # Retrieve full object (in case we only got Model(id='id'))
        org_obj = self.db_store2.get_one(obj)
        if org_obj:
            org_obj.emit_deleted()
            self.db_store2.delete(org_obj)
        else:
            # NOTE(nick-ma-z): Ignore the null object because
            # it has been deleted before.
            pass

    def get_nb_api(self):
        return self.nb_api

    def get_db_store(self):
        return self.db_store

    def get_openflow_app(self):
        return self.open_flow_app

    def get_chassis_name(self):
        return self.chassis_name

    def notify_port_status(self, ovs_port, status):
        if self.neutron_notifier:
            self.neutron_notifier.notify_port_status(ovs_port, status)

    def _get_delete_handler(self, table):
        method_name = 'delete_{0}'.format(table)
        return getattr(self, method_name, self.delete_model_object)

    def update(self, obj):
        handler = getattr(
            self,
            'update_{0}'.format(obj.table_name),
            self.update_model_object,
        )
        return handler(obj)

    def delete(self, obj):
        handler = self._get_delete_handler(obj.table_name)

        if isinstance(obj, models.NbDbObject):
            return handler(obj.id)
        else:
            return handler(obj)

    def delete_by_id(self, model, obj_id):
        # FIXME (dimak) Probably won't be needed once we're done porting
        handler = self._get_delete_handler(model.table_name)

        if issubclass(model, models.NbObject):
            return handler(obj_id)
        else:
            return handler(model(id=obj_id))


def init_ryu_config():
    ryu_cfg.CONF(project='ryu', args=[])
    ryu_cfg.CONF.ofp_listen_host = cfg.CONF.df_ryu.of_listen_address
    ryu_cfg.CONF.ofp_tcp_listen_port = cfg.CONF.df_ryu.of_listen_port


# Run this application like this:
# python df_local_controller.py <chassis_unique_name>
# <local ip address> <southbound_db_ip_address>
def main():
    chassis_name = cfg.CONF.host
    common_config.init(sys.argv[1:])
    common_config.setup_logging()
    init_ryu_config()
    controller = DfLocalController(chassis_name)
    controller.run()
