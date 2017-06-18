# Copyright (c) 2016 OpenStack Foundation.
#
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

import netaddr
from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.rpc.handlers import l3_rpc
from neutron.common import exceptions as n_common_exc
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.db import common_db_mixin
from neutron.db import extraroute_db
from neutron.db import l3_agentschedulers_db
from neutron.db import l3_attrs_db
from neutron.db import l3_gwmode_db
from neutron.db.models import l3 as l3_db
from neutron.quota import resource_registry
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import constants as const
from neutron_lib.plugins import directory
from neutron_lib.services import base as service_base
from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import importutils

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.neutron.common import constants as df_const
from dragonflow.neutron.db.models import l3 as neutron_l3
from dragonflow.neutron.services import mixins


LOG = log.getLogger(__name__)


class DFL3RouterPlugin(service_base.ServicePluginBase,
                       common_db_mixin.CommonDbMixin,
                       extraroute_db.ExtraRoute_dbonly_mixin,
                       l3_gwmode_db.L3_NAT_db_mixin,
                       l3_attrs_db.ExtraAttributesMixin,
                       l3_agentschedulers_db.L3AgentSchedulerDbMixin,
                       mixins.LazyNbApiMixin):

    """Implementation of the Dragonflow Neutron L3 Router Service Plugin.

    This class implements a L3 service plugin that provides
    router, floatingip resources and manages associated
    request/response.
    """

    supported_extension_aliases = ["router", "extraroute",
                                   "l3_agent_scheduler"]

    @resource_registry.tracked_resources(
        router=l3_db.Router,
        floatingip=l3_db.FloatingIP)
    def __init__(self):
        self.router_scheduler = importutils.import_object(
            cfg.CONF.router_scheduler_driver)
        super(DFL3RouterPlugin, self).__init__()
        self._nb_api = None
        self._start_rpc_notifiers()
        self._register_callbacks()

    @property
    def core_plugin(self):
        return directory.get_plugin()

    def _register_callbacks(self):
        registry.subscribe(self.router_create_callback,
                           resources.ROUTER,
                           events.PRECOMMIT_CREATE)

    def router_create_callback(self, resource, event, trigger, context,
                               router, router_db, **kwargs):
        with context.session.begin(subtransactions=True):
            self._ensure_extra_attr_model(context, router_db)

    def _start_rpc_notifiers(self):
        """Initialization RPC notifiers for agents"""
        self.agent_notifiers[const.AGENT_TYPE_L3] = {
            l3_rpc_agent_api.L3AgentNotifyAPI()
        }

    def start_rpc_listeners(self):
        self.topic = topics.L3PLUGIN
        self.conn = n_rpc.create_connection()
        self.agent_notifiers.update(
            {const.AGENT_TYPE_L3: l3_rpc_agent_api.L3AgentNotifyAPI()})
        self.endpoints = [l3_rpc.L3RpcCallback()]
        self.conn.create_consumer(self.topic, self.endpoints,
                                  fanout=False)
        return self.conn.consume_in_threads()

    def get_plugin_type(self):
        return const.L3

    def get_plugin_description(self):
        """Returns string description of the plugin."""
        return ("L3 Router Service Plugin for basic L3 forwarding "
                "using Dragonflow.")

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_router(self, context, router):
        router = super(DFL3RouterPlugin, self).create_router(context, router)
        lrouter = neutron_l3.logical_router_from_neutron_router(router)
        self.nb_api.create(lrouter)
        return router

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def update_router(self, context, router_id, router):
        router = super(DFL3RouterPlugin, self).update_router(
                       context, router_id, router)
        lrouter = neutron_l3.logical_router_from_neutron_router(router)
        try:
            self.nb_api.update(lrouter)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB", router_id)

        return router

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def delete_router(self, context, router_id):
        ret_val = super(DFL3RouterPlugin, self).delete_router(context,
                                                              router_id)
        try:
            self.nb_api.delete(l3.LogicalRouter(id=router_id))
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB", router_id)
        return ret_val

    def _get_floatingip_port(self, context, floatingip_id):
        filters = {'device_id': [floatingip_id]}
        floating_ports = self.core_plugin.get_ports(context, filters=filters)
        if floating_ports:
            return floating_ports[0]
        return None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_floatingip(self, context, floatingip):
        floatingip_port = None
        try:
            floatingip_dict = super(DFL3RouterPlugin, self).create_floatingip(
                context, floatingip,
                initial_status=const.FLOATINGIP_STATUS_DOWN)
            # Note: Here the context is elevated, because the floatingip port
            # will not have tenant and floatingip subnet might be in other
            # tenant.
            admin_context = context.elevated()
            floatingip_port = self._get_floatingip_port(
                admin_context, floatingip_dict['id'])
            if not floatingip_port:
                raise n_common_exc.DeviceNotFoundError(
                    device_name=floatingip_dict['id'])
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = True
                # delete the stale floatingip port
                try:
                    if floatingip_port:
                        self.nb_api.delete(
                            l2.LogicalPort(id=floatingip_port['id'],
                                           topic=floatingip_port['tenant_id']))
                except df_exceptions.DBKeyNotFound:
                    pass

        self.nb_api.create(
            l3.FloatingIp(
                id=floatingip_dict['id'],
                topic=floatingip_dict['tenant_id'],
                name=floatingip_dict.get('name', df_const.DF_FIP_DEFAULT_NAME),
                version=floatingip_dict['revision_number'],
                status=floatingip_dict['status'],
                floating_ip_address=floatingip_dict['floating_ip_address'],
                fixed_ip_address=floatingip_dict['fixed_ip_address'],
                lrouter=floatingip_dict['router_id'],
                lport=floatingip_dict['port_id'],
                floating_lport=floatingip_port['id'],
            ),
        )

        return floatingip_dict

    @lock_db.wrap_db_lock(lock_db.RESOURCE_FIP_UPDATE_OR_DELETE)
    def update_floatingip(self, context, id, floatingip):
        floatingip_dict = super(DFL3RouterPlugin, self).update_floatingip(
            context, id, floatingip)

        self.nb_api.update(
            l3.FloatingIp(
                id=floatingip_dict['id'],
                topic=floatingip_dict['tenant_id'],
                name=floatingip_dict.get('name', df_const.DF_FIP_DEFAULT_NAME),
                version=floatingip_dict['revision_number'],
                lrouter=floatingip_dict['router_id'],
                lport=floatingip_dict['port_id'],
                fixed_ip_address=floatingip_dict['fixed_ip_address'],
            ),
        )
        return floatingip_dict

    @lock_db.wrap_db_lock(lock_db.RESOURCE_FIP_UPDATE_OR_DELETE)
    def delete_floatingip(self, context, fip_id):
        floatingip = self.get_floatingip(context, fip_id)
        super(DFL3RouterPlugin, self).delete_floatingip(context, fip_id)
        try:
            self.nb_api.delete(
                l3.FloatingIp(id=fip_id, topic=floatingip['tenant_id']),
            )
        except df_exceptions.DBKeyNotFound:
            LOG.exception("floatingip %s is not found in DF DB", fip_id)

    def update_fip_status(self, context, fip_id, status):
        self.nb_api.update(
            l3.FloatingIp(
                id=fip_id,
                status=status,
            ),
            skip_send_event=True,
        )
        self.update_floatingip_status(context, fip_id, status)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def add_router_interface(self, context, router_id, interface_info):
        router_port_info = super(DFL3RouterPlugin, self).add_router_interface(
            context, router_id, interface_info)
        router = self.get_router(context, router_id)

        port = self.core_plugin.get_port(context, router_port_info['port_id'])
        subnet = self.core_plugin.get_subnet(context,
                                             router_port_info['subnet_id'])
        cidr = netaddr.IPNetwork(subnet['cidr'])
        network = "%s/%s" % (port['fixed_ips'][0]['ip_address'],
                             str(cidr.prefixlen))
        logical_port = self.nb_api.get(l2.LogicalPort(id=port['id'],
                                                      topic=port['tenant_id']))

        logical_router_port = neutron_l3.build_logical_router_port(
            router_port_info, mac=port['mac_address'],
            network=network, unique_key=logical_port.unique_key)
        lrouter = self.nb_api.get(l3.LogicalRouter(id=router_id,
                                                   topic=router['tenant_id']))
        lrouter.version = router['revision_number']
        lrouter.add_router_port(logical_router_port)
        self.nb_api.update(lrouter)

        return router_port_info

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def remove_router_interface(self, context, router_id, interface_info):
        router_port_info = (
            super(DFL3RouterPlugin, self).remove_router_interface(
                context, router_id, interface_info))
        router = self.get_router(context, router_id)

        try:
            lrouter = self.nb_api.get(l3.LogicalRouter(
                id=router_id, topic=router['tenant_id']))
            lrouter.remove_router_port(router_port_info['port_id'])
            lrouter.version = router['revision_number']
            self.nb_api.update(lrouter)
        except df_exceptions.DBKeyNotFound:
            LOG.exception("logical router %s is not found in DF DB, "
                          "suppressing delete_lrouter_port "
                          "exception", router_id)
        return router_port_info

    def get_number_of_agents_for_scheduling(self, context):
        """Return number of agents on which the router will be scheduled.
        Taken from Neutron's L3_HA_NAT_db_mixin.
        """

        l3_agents_filters = {'agent_modes': [const.L3_AGENT_MODE_LEGACY,
                                             const.L3_AGENT_MODE_DVR_SNAT]}
        num_agents = len(self.get_l3_agents(context, active=True,
                                            filters=l3_agents_filters))
        max_agents = cfg.CONF.max_l3_agents_per_router
        if max_agents:
            if max_agents > num_agents:
                LOG.info("Number of active agents lower than "
                         "max_l3_agents_per_router. L3 agents "
                         "available: %s", num_agents)
            else:
                num_agents = max_agents

        return num_agents
