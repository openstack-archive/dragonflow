# Copyright (c) 2015 OpenStack Foundation.
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

from neutron.common import constants as const
from neutron.common import exceptions as n_exc
from neutron.db import common_db_mixin
from neutron.db import db_base_plugin_v2
from neutron.db import extraroute_db
from neutron.db import l3_db
from neutron.db import securitygroups_db
from neutron import manager
from neutron.plugins.common import constants
from neutron.quota import resource_registry
from neutron.services import service_base

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import api_nb
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.db.neutron import versionobjects_db as version_db
from dragonflow.neutron.common import constants as df_const


LOG = log.getLogger(__name__)


class DFL3RouterPlugin(service_base.ServicePluginBase,
                       db_base_plugin_v2.NeutronDbPluginV2,
                       common_db_mixin.CommonDbMixin,
                       extraroute_db.ExtraRoute_db_mixin,
                       l3_db.L3_NAT_dbonly_mixin):

    """Implementation of the Dragonflow Neutron L3 Router Service Plugin.

    This class implements a L3 service plugin that provides
    router, floatingip and security_group resources and manages associated
    request/response.
    """
    supported_extension_aliases = ["router", "extraroute", "security-group"]

    @resource_registry.tracked_resources(
        outer=l3_db.Router,
        floatingip=l3_db.FloatingIP,
        security_group=securitygroups_db.SecurityGroup,
        security_group_rule=securitygroups_db.SecurityGroupRule)
    def __init__(self):
        super(DFL3RouterPlugin, self).__init__()
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(
                nb_driver_class(),
                use_pubsub=cfg.CONF.df.enable_df_pub_sub,
                is_neutron_server=True)
        # TODO(hshan) provide interface to get nb_api
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)
        self.core_plugin = None

    def get_plugin_type(self):
        return constants.L3_ROUTER_NAT

    def get_plugin_description(self):
        """Returns string description of the plugin."""
        return ("L3 Router Service Plugin for basic L3 forwarding "
                "using Dragonflow.")

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_router(self, context, router):
        with context.session.begin(subtransactions=True):
            router = super(DFL3RouterPlugin, self).create_router(
                context, router)
            router_version = version_db._create_db_version_row(
                context.session, router['id']
            )

        router_id = router['id']
        tenant_id = router['tenant_id']
        is_distributed = router.get('distributed', False)
        router_name = router.get('name', df_const.DF_RESOURCE_DEFAULT_NAME)
        self.nb_api.create_lrouter(router_id, topic=tenant_id,
                                   name=router_name,
                                   distributed=is_distributed,
                                   version=router_version,
                                   ports=[])
        return router

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def update_router(self, context, router_id, router):
        with context.session.begin(subtransactions=True):
            router = super(DFL3RouterPlugin, self).update_router(
                context, router_id, router)
            router_version = version_db._update_db_version_row(
                    context.session, router['id'])

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
                gateway=(gw_info if gw_info else {})
            )
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB, might have "
                      "been deleted concurrently" % router_id)

        return router

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def delete_router(self, context, router_id):
        router = self.get_router(context, router_id)
        with context.session.begin(subtransactions=True):
            ret_val = super(DFL3RouterPlugin, self).delete_router(context,
                                                                  router_id)
            version_db._delete_db_version_row(context.session, router_id)
        try:
            self.nb_api.delete_lrouter(id=router_id,
                                       topic=router['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB, might have "
                      "been deleted concurrently" % router_id)
        return ret_val

    def _get_floatingip_port(self, context, floatingip_id):
        filters = {'device_id': [floatingip_id]}
        floating_ports = self.get_ports(context, filters=filters)
        if floating_ports:
            return floating_ports[0]
        return None

    def _get_floatingip_subnet(self, context, subnet_id):
        gateway_subnet = self.get_subnet(context, subnet_id)
        if gateway_subnet['ip_version'] == 4:
            return gateway_subnet
        return None

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_floatingip(self, context, floatingip):
        try:
            floatingip_port = None
            with context.session.begin(subtransactions=True):
                floatingip_dict = \
                    super(DFL3RouterPlugin, self).create_floatingip(
                        context,
                        floatingip,
                        initial_status=const.FLOATINGIP_STATUS_DOWN)
                fip_version = version_db._create_db_version_row(
                    context.session, floatingip_dict['id']
                )

                floatingip_port = self._get_floatingip_port(
                    context, floatingip_dict['id'])
                if not floatingip_port:
                    raise n_exc.DeviceNotFoundError(
                        device_name=floatingip_dict['id'])
                subnet_id = floatingip_port['fixed_ips'][0]['subnet_id']
                floatingip_subnet = self._get_floatingip_subnet(
                    context, subnet_id)
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

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def update_floatingip(self, context, id, floatingip):
        with context.session.begin(subtransactions=True):
            floatingip_dict = super(DFL3RouterPlugin, self).update_floatingip(
                context, id, floatingip)
            fip_version = version_db._update_db_version_row(
                context.session, id)

        self.nb_api.update_floatingip(
            id=floatingip_dict['id'],
            topic=floatingip_dict['tenant_id'],
            notify=True,
            name=floatingip_dict.get('name', df_const.DF_FIP_DEFAULT_NAME),
            router_id=floatingip_dict['router_id'],
            port_id=floatingip_dict['port_id'],
            version=fip_version,
            fixed_ip_address=floatingip_dict['fixed_ip_address'],
            status=floatingip_dict['status'])
        return floatingip_dict

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def delete_floatingip(self, context, id):
        with context.session.begin(subtransactions=True):
            floatingip = self.get_floatingip(context, id)
            super(DFL3RouterPlugin, self).delete_floatingip(context, id)
            version_db._delete_db_version_row(context.session, id)
        try:
            self.nb_api.delete_floatingip(id=id,
                                          topic=floatingip['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("floatingip %s is not found in DF DB, might have "
                      "been deleted concurrently" % id)

    def get_floatingip(self, context, id, fields=None):
        with context.session.begin(subtransactions=True):
            fip = super(DFL3RouterPlugin, self).get_floatingip(context, id,
                                                               fields)
            fip['status'] = self.nb_api.get_floatingip(id).get_status()
            return fip

    def _get_core_plugin(self):
        if not self.core_plugin:
            self.core_plugin = manager.NeutronManager.get_plugin()
        return self.core_plugin

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def add_router_interface(self, context, router_id, interface_info):
        with context.session.begin(subtransactions=True):
            result = super(DFL3RouterPlugin, self).add_router_interface(
                context, router_id, interface_info)
            router_version = version_db._update_db_version_row(
                context.session, router_id)

        self.core_plugin = self._get_core_plugin()
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
                                     tunnel_key=logical_port.get_tunnel_key())
        return result

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def remove_router_interface(self, context, router_id, interface_info):
        with context.session.begin(subtransactions=True):
            new_router = super(DFL3RouterPlugin, self).remove_router_interface(
                context, router_id, interface_info)
            router_version = version_db._update_db_version_row(
                context.session, router_id)

        self.core_plugin = self._get_core_plugin()
        subnet = self.core_plugin.get_subnet(context, new_router['subnet_id'])
        network_id = subnet['network_id']

        try:
            self.nb_api.delete_lrouter_port(router_id,
                                            network_id,
                                            subnet['tenant_id'],
                                            router_version=router_version)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("logical router %s is not found in DF DB, "
                      "suppressing delete_lrouter_port "
                      "exception" % router_id)
        return new_router

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_security_group(
            self, context, security_group, default_sg=False):
        with context.session.begin(subtransactions=True):
            sg_db = super(DFL3RouterPlugin,
                          self).create_security_group(context, security_group,
                                                      default_sg)
            sg_version = version_db._create_db_version_row(
                    context.session, sg_db['id'])
        sg_id = sg_db['id']
        sg_name = sg_db.get('name', df_const.DF_SG_DEFAULT_NAME)
        tenant_id = sg_db['tenant_id']
        rules = sg_db.get('security_group_rules')
        for rule in rules:
            rule['topic'] = rule.get('tenant_id')
            del rule['tenant_id']

        self.nb_api.create_security_group(id=sg_id, topic=tenant_id,
                                          name=sg_name, rules=rules,
                                          version=sg_version)
        return sg_db

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def update_security_group(self, context, sg_id, security_group):
        with context.session.begin(subtransactions=True):
            sg_db = super(DFL3RouterPlugin,
                          self).update_security_group(context, sg_id,
                                                      security_group)
            sg_version = version_db._update_db_version_row(
                    context.session, sg_id)

        sg_name = sg_db.get('name', df_const.DF_SG_DEFAULT_NAME)
        tenant_id = sg_db['tenant_id']
        rules = sg_db.get('security_group_rules')

        self.nb_api.update_security_group(id=sg_id, topic=tenant_id,
                                          name=sg_name, rules=rules,
                                          version=sg_version)
        return sg_db

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_security_group_rule(self, context, security_group_rule):
        with context.session.begin(subtransactions=True):
            sg_rule = super(DFL3RouterPlugin, self).create_security_group_rule(
                context, security_group_rule)
            sg_id = sg_rule['security_group_id']
            sg_version_id = version_db._update_db_version_row(
                    context.session, sg_id)
            sg_group = self.get_security_group(context, sg_id)
        sg_rule['topic'] = sg_rule.get('tenant_id')
        del sg_rule['tenant_id']
        self.nb_api.add_security_group_rules(sg_id, sg_group['tenant_id'],
                                             sg_rules=[sg_rule],
                                             sg_version=sg_version_id)
        return sg_rule

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def delete_security_group_rule(self, context, id):
        with context.session.begin(subtransactions=True):
            security_group_rule = self.get_security_group_rule(context, id)
            sg_id = security_group_rule['security_group_id']
            sg_group = self.get_security_group(context, sg_id)
            super(DFL3RouterPlugin, self).delete_security_group_rule(
                context, id)
            sg_version_id = version_db._update_db_version_row(
                    context.session, sg_id)
        self.nb_api.delete_security_group_rule(sg_id, id,
                                               sg_group['tenant_id'],
                                               sg_version=sg_version_id)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def delete_security_group(self, context, sg_id):
        sg = self.get_security_group(context, sg_id)
        tenant_id = sg['tenant_id']
        with context.session.begin(subtransactions=True):
            super(DFL3RouterPlugin, self).delete_security_group(context, sg_id)
            version_db._delete_db_version_row(
                    context.session, sg_id)
        self.nb_api.delete_security_group(sg_id, topic=tenant_id)
