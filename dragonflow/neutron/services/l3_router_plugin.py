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

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import importutils

from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.rpc.handlers import l3_rpc
from neutron.common import exceptions as n_common_exc
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.db import common_db_mixin
from neutron.db import extraroute_db
from neutron.db import l3_agentschedulers_db
from neutron.db import l3_gwmode_db
from neutron.db.models import l3 as l3_db
from neutron.quota import resource_registry
from neutron.services import service_base
from neutron_lib import constants as const
from neutron_lib import exceptions as n_exc
from neutron_lib.plugins import directory

from dragonflow._i18n import _LE
from dragonflow.common import exceptions as df_exceptions
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.neutron.common import constants as df_const


LOG = log.getLogger(__name__)


class DFL3RouterPlugin(service_base.ServicePluginBase,
                       common_db_mixin.CommonDbMixin,
                       extraroute_db.ExtraRoute_db_mixin,
                       l3_gwmode_db.L3_NAT_db_mixin,
                       l3_agentschedulers_db.L3AgentSchedulerDbMixin):

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

    @property
    def core_plugin(self):
        return directory.get_plugin()

    @property
    def nb_api(self):
        if self._nb_api is None:
            plugin = self.core_plugin
            mech_driver = plugin.mechanism_manager.mech_drivers['df'].obj
            self._nb_api = mech_driver.nb_api

        return self._nb_api

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
        router_version = router['revision_number']
        router_id = router['id']
        tenant_id = router['tenant_id']
        is_distributed = router.get('distributed', False)
        router_name = router.get('name', df_const.DF_ROUTER_DEFAULT_NAME)
        self.nb_api.create_lrouter(router_id, topic=tenant_id,
                                   name=router_name,
                                   distributed=is_distributed,
                                   version=router_version,
                                   ports=[])
        return router

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def update_router(self, context, router_id, router):
        router = super(DFL3RouterPlugin, self).update_router(
                       context, router_id, router)
        router_version = router['revision_number']

        try:
            gw_info = router.get('external_gateway_info', {})
            if gw_info:
                gw_info.update({'port_id': router.get('gw_port_id')})
            is_distributed = router.get('distributed', False)
            self.nb_api.update_lrouter(
                router_id,
                topic=router['tenant_id'],
                name=router['name'],
                distributed=is_distributed,
                version=router_version,
                routes=router.get('routes', []),
                admin_state_up=router['admin_state_up'],
                description=router['description'],
                gateway=gw_info
            )
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB" % router_id)

        return router

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def delete_router(self, context, router_id):
        router = self.get_router(context, router_id)
        ret_val = super(DFL3RouterPlugin, self).delete_router(context,
                                                              router_id)
        try:
            self.nb_api.delete_lrouter(id=router_id,
                                       topic=router['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB" % router_id)
        return ret_val

    def _get_floatingip_port(self, context, floatingip_id):
        filters = {'device_id': [floatingip_id]}
        floating_ports = self.core_plugin.get_ports(context, filters=filters)
        if floating_ports:
            return floating_ports[0]
        return None

    def _get_floatingip_subnet(self, context, subnet_id):
        gateway_subnet = self.core_plugin.get_subnet(context, subnet_id)
        if gateway_subnet['ip_version'] == 4:
            return gateway_subnet
        return None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_floatingip(self, context, floatingip):
        floatingip_port = None
        try:
            floatingip_dict = super(DFL3RouterPlugin, self).create_floatingip(
                context, floatingip,
                initial_status=const.FLOATINGIP_STATUS_DOWN)
            fip_version = floatingip_dict['revision_number']
            # Note: Here the context is elevated, because the floatingip port
            # will not have tenant and floatingip subnet might be in other
            # tenant.
            admin_context = context.elevated()
            floatingip_port = self._get_floatingip_port(
                admin_context, floatingip_dict['id'])
            if not floatingip_port:
                raise n_common_exc.DeviceNotFoundError(
                    device_name=floatingip_dict['id'])
            subnet_id = floatingip_port['fixed_ips'][0]['subnet_id']
            floatingip_subnet = self._get_floatingip_subnet(
                admin_context, subnet_id)
            if floatingip_subnet is None:
                raise n_exc.SubnetNotFound(subnet_id=subnet_id)
        except Exception:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = True
                # delete the stale floatingip port
                try:
                    if floatingip_port:
                        self.nb_api.delete_lport(floatingip_port['id'],
                                                 floatingip_port['tenant_id'])
                except df_exceptions.DBKeyNotFound:
                    pass

        self.nb_api.create_floatingip(
                id=floatingip_dict['id'],
                topic=floatingip_dict['tenant_id'],
                name=floatingip_dict.get('name', df_const.DF_FIP_DEFAULT_NAME),
                floating_ip_address=floatingip_dict['floating_ip_address'],
                floating_network_id=floatingip_dict['floating_network_id'],
                router_id=floatingip_dict['router_id'],
                port_id=floatingip_dict['port_id'],
                fixed_ip_address=floatingip_dict['fixed_ip_address'],
                status=floatingip_dict['status'],
                floating_port_id=floatingip_port['id'],
                floating_mac_address=floatingip_port['mac_address'],
                external_gateway_ip=floatingip_subnet['gateway_ip'],
                version=fip_version,
                external_cidr=floatingip_subnet['cidr'])

        return floatingip_dict

    @lock_db.wrap_db_lock(lock_db.RESOURCE_FIP_UPDATE_OR_DELETE)
    def update_floatingip(self, context, id, floatingip):
        floatingip_dict = super(DFL3RouterPlugin, self).update_floatingip(
            context, id, floatingip)
        fip_version = floatingip_dict['revision_number']

        self.nb_api.update_floatingip(
            id=floatingip_dict['id'],
            topic=floatingip_dict['tenant_id'],
            notify=True,
            name=floatingip_dict.get('name', df_const.DF_FIP_DEFAULT_NAME),
            router_id=floatingip_dict['router_id'],
            port_id=floatingip_dict['port_id'],
            version=fip_version,
            fixed_ip_address=floatingip_dict['fixed_ip_address'])
        return floatingip_dict

    @lock_db.wrap_db_lock(lock_db.RESOURCE_FIP_UPDATE_OR_DELETE)
    def delete_floatingip(self, context, id):
        floatingip = self.get_floatingip(context, id)
        super(DFL3RouterPlugin, self).delete_floatingip(context, id)
        try:
            self.nb_api.delete_floatingip(id=id,
                                          topic=floatingip['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.exception(_LE("floatingip %s is not found in DF DB") % id)

    def get_floatingip(self, context, id, fields=None):
        with context.session.begin(subtransactions=True):
            fip = super(DFL3RouterPlugin, self).get_floatingip(context, id,
                                                               fields)
            fip['status'] = self.nb_api.get_floatingip(id).get_status()
            return fip

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def add_router_interface(self, context, router_id, interface_info):
        result = super(DFL3RouterPlugin, self).add_router_interface(
                       context, router_id, interface_info)
        router = self.get_router(context, router_id)
        router_version = router['revision_number']

        port = self.core_plugin.get_port(context, result['port_id'])
        subnet = self.core_plugin.get_subnet(context, result['subnet_id'])
        cidr = netaddr.IPNetwork(subnet['cidr'])
        network = "%s/%s" % (port['fixed_ips'][0]['ip_address'],
                             str(cidr.prefixlen))
        logical_port = self.nb_api.get_logical_port(port['id'],
                                                    port['tenant_id'])

        self.nb_api.add_lrouter_port(result['port_id'],
                                     result['id'],
                                     result['network_id'],
                                     result['tenant_id'],
                                     router_version=router_version,
                                     mac=port['mac_address'],
                                     network=network,
                                     unique_key=logical_port.get_unique_key())
        return result

    @lock_db.wrap_db_lock(lock_db.RESOURCE_ROUTER_UPDATE_OR_DELETE)
    def remove_router_interface(self, context, router_id, interface_info):
        router_port_info = (
            super(DFL3RouterPlugin, self).remove_router_interface(
                context, router_id, interface_info))
        router = self.get_router(context, router_id)
        router_version = router['revision_number']

        try:
            self.nb_api.delete_lrouter_port(router_port_info['port_id'],
                                            router_id,
                                            router_port_info['tenant_id'],
                                            router_version=router_version)
        except df_exceptions.DBKeyNotFound:
            LOG.exception(_LE("logical router %s is not found in DF DB, "
                              "suppressing delete_lrouter_port "
                              "exception") % router_id)
        return router_port_info
