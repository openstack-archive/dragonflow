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
from ryu.app.ofctl import service as of_service
from ryu.base import app_manager
from ryu import cfg as ryu_cfg

from dragonflow.common import constants
from dragonflow.common import utils as df_utils
from dragonflow import conf as cfg
from dragonflow.controller import df_db_objects_refresh
from dragonflow.controller import ryu_base_app
from dragonflow.controller import service
from dragonflow.controller import topology
from dragonflow.db import api_nb
from dragonflow.db import db_consistent
from dragonflow.db import db_store
from dragonflow.db import model_framework
from dragonflow.db import model_proxy
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.db.models import mixins
from dragonflow.db.models import trunk
from dragonflow.ovsdb import vswitch_impl


LOG = log.getLogger(__name__)


class DfLocalController(object):

    def __init__(self, chassis_name, nb_api):
        self.db_store = db_store.get_instance()

        self.chassis_name = chassis_name
        self.nb_api = nb_api
        self.ip = cfg.CONF.df.local_ip
        # Virtual tunnel port support multiple tunnel types together
        self.tunnel_types = cfg.CONF.df.tunnel_types
        self.sync_finished = False
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
            neutron_server_notifier=self.neutron_notifier,
        )
        # The OfctlService is needed to support the 'get_flows' method
        self.open_flow_service = app_mgr.instantiate(of_service.OfctlService)
        self.topology = None
        self.db_consistency_manager = None
        self.enable_db_consistency = cfg.CONF.df.enable_df_db_consistency
        self.enable_selective_topo_dist = \
            cfg.CONF.df.enable_selective_topology_distribution

    def run(self):
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
        self.open_flow_service.start()
        self.open_flow_app.start()
        self.create_tunnels()
        self._register_models()
        self.db_sync_loop()

    def _register_models(self):
        for model in model_framework.iter_models_by_dependency_order():
            # FIXME (dimak) do not register topicless models for now
            if issubclass(model, mixins.Topic):
                df_db_objects_refresh.add_refresher(
                    df_db_objects_refresh.DfObjectRefresher(
                        model.__name__,
                        functools.partial(self.db_store.get_keys_by_topic,
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
            LOG.warning("run_db_poll - suppressing exception")
            LOG.exception(e)

    def update_chassis(self, chassis):
        self.db_store.update(chassis)
        remote_chassis_name = chassis.id
        if self.chassis_name == remote_chassis_name:
            return

        # Notify about remote port update
        index = l2.LogicalPort.get_index('chassis_id')
        remote_ports = self.db_store.get_all(l2.LogicalPort(chassis=chassis),
                                             index=index)
        for port in remote_ports:
            self._logical_port_process(port)

    def delete_chassis(self, chassis):
        LOG.info("Deleting remote ports in remote chassis %s", chassis.id)
        # Chassis is deleted, there is no reason to keep the remote port
        # in it.
        index = l2.LogicalPort.get_indexes()['chassis_id']
        remote_ports = self.db_store.get_all(l2.LogicalPort(chassis=chassis),
                                             index=index)
        for port in remote_ports:
            self._delete_lport_instance(port)
        self.db_store.delete(chassis)

    def _is_physical_chassis(self, chassis):
        if not chassis:
            return False
        if chassis.id == constants.DRAGONFLOW_VIRTUAL_PORT:
            return False
        if model_proxy.is_model_proxy(chassis) and not chassis.get_object():
            return False
        return True

    # REVISIT(oanson) The special handling of logical port process should be
    # removed from DF controller. (bug/1690775)
    def _logical_port_process(self, lport):
        lswitch = lport.lswitch
        if not lswitch:
            LOG.warning("Could not find lswitch for lport: %s",
                        lport.id)
            return

        chassis = lport.chassis
        is_local = (chassis.id == self.chassis_name)
        lport.is_local = is_local
        l2_tunnel = lswitch.network_type in self.tunnel_types
        if is_local:
            if not lport.ofport:
                lport.ofport = self.vswitch_api.get_port_ofport_by_id(lport.id)
            if not lport.ofport:
                # Not attached to the switch. Maybe it's a subport?
                lport.ofport = self._get_trunk_subport_ofport(lport)
        elif l2_tunnel:
                lport.peer_vtep_address = (
                        chassis.id if lport.remote_vtep else chassis.ip)
                lport.ofport = self.vswitch_api.get_vtp_ofport(
                        lswitch.network_type)

        if l2_tunnel and lport.ofport is None:
            # The tunnel port online event will update the remote logical
            # port. Log this warning first.
            LOG.warning("%(location)s logical port %(port)s"
                        " was not created yet",
                        {'location': "Local" if is_local else
                                     "Tunnel for remote",
                         'port': lport})
            return

        original_lport = self.db_store.get_one(lport)
        self.db_store.update(lport)
        if original_lport is None:
            lport.emit_created()
        else:
            lport.emit_updated(original_lport)

    def _get_trunk_subport_ofport(self, lport):
        try:
            cps = self.db_store.get_one(
                    trunk.ChildPortSegmentation(port=lport.id),
                    trunk.ChildPortSegmentation.get_index('lport_id'))
            if cps:
                return cps.parent.ofport
        except Exception:
            # Not found. Do nothing
            pass

    def update_lport(self, lport):
        chassis = lport.chassis
        if (not lport.remote_vtep and
                not self._is_physical_chassis(chassis)):
            LOG.debug(("Port %s has not been bound or it is a vPort"),
                      lport.id)
            return
        original_lport = self.db_store.get_one(lport)

        if lport.is_newer_than(original_lport):
            self._logical_port_process(lport)

    def delete_lport(self, lport):
        lport = self.db_store.get_one(lport)
        if lport is None:
            return
        self._delete_lport_instance(lport)

    def _delete_lport_instance(self, lport):
        lport.emit_deleted()
        self.db_store.delete(lport)

    def register_chassis(self):
        # Get all chassis from nb db to db store.
        for c in self.nb_api.get_all(core.Chassis):
            self.db_store.update(c)

        old_chassis = self.db_store.get_one(
            core.Chassis(id=self.chassis_name))

        chassis = core.Chassis(
            id=self.chassis_name,
            ip=self.ip,
            tunnel_types=self.tunnel_types,
        )
        if cfg.CONF.df.external_host_ip:
            chassis.external_host_ip = cfg.CONF.df.external_host_ip

        self.db_store.update(chassis)

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

    def update_publisher(self, publisher):
        self.db_store.update(publisher)
        LOG.info('Registering to new publisher: %s', str(publisher))
        self.nb_api.subscriber.register_listen_address(publisher.uri)

    def delete_publisher(self, publisher):
        LOG.info('Deleting publisher: %s', str(publisher))
        self.nb_api.subscriber.unregister_listen_address(publisher.uri)
        self.db_store.delete(publisher)

    # TODO(dimak) have ovs ports behave like rest of the modes and store
    #             in db_store.
    def update_ovs_port(self, ovs_port):
        ovs_port.emit_updated()

    def delete_ovs_port(self, ovs_port):
        ovs_port.emit_deleted()

    def ovs_sync_finished(self):
        self.open_flow_app.notify_ovs_sync_finished()

    def ovs_sync_started(self):
        self.open_flow_app.notify_ovs_sync_started()

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
        original_obj = self.db_store.get_one(obj)
        if original_obj is None:
            obj.emit_created()
        elif self._is_newer(obj, original_obj):
            obj.emit_updated(original_obj)
        else:
            return

        self.db_store.update(obj)

    def delete_model_object(self, obj):
        # Retrieve full object (in case we only got Model(id='id'))
        org_obj = self.db_store.get_one(obj)
        if org_obj:
            org_obj.emit_deleted()
            self.db_store.delete(org_obj)
        else:
            # NOTE(nick-ma-z): Ignore the null object because
            # it has been deleted before.
            pass

    def get_nb_api(self):
        return self.nb_api

    def get_chassis_name(self):
        return self.chassis_name

    def notify_port_status(self, ovs_port, status):
        if self.neutron_notifier:
            self.neutron_notifier.notify_port_status(ovs_port, status)

    def _get_delete_handler(self, table):
        method_name = 'delete_{0}'.format(table)
        return getattr(self, method_name, self.delete_model_object)

    def update_child_port_segmentation(self, obj):
        self.update_model_object(obj)
        child = obj.port.get_object()
        if child:
            self.update(child)

    def update(self, obj):
        handler = getattr(
            self,
            'update_{0}'.format(obj.table_name),
            self.update_model_object,
        )
        return handler(obj)

    def delete(self, obj):
        handler = self._get_delete_handler(obj.table_name)
        return handler(obj)

    def delete_by_id(self, model, obj_id):
        # FIXME (dimak) Probably won't be needed once we're done porting
        return self.delete(model(id=obj_id))


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
    nb_api = api_nb.NbApi.get_instance(False)
    controller = DfLocalController(chassis_name, nb_api)
    service.register_service('df-local-controller', nb_api, controller)
    controller.run()
