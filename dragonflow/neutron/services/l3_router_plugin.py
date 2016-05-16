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

from neutron.api.v2 import attributes as attr
from neutron.common import constants as const
from neutron.common import exceptions as n_exc
from neutron.db import common_db_mixin
from neutron.db import db_base_plugin_v2
from neutron.db import extraroute_db
from neutron.db import l3_db
from neutron.db import l3_gwmode_db
from neutron.plugins.common import constants
from neutron.services import service_base

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import api_nb
from dragonflow.neutron.common import constants as df_const


LOG = log.getLogger(__name__)


class DFL3RouterPlugin(service_base.ServicePluginBase,
                       db_base_plugin_v2.NeutronDbPluginV2,
                       common_db_mixin.CommonDbMixin,
                       extraroute_db.ExtraRoute_db_mixin,
                       l3_gwmode_db.L3_NAT_db_mixin):

    """Implementation of the Neutron L3 Router Service Plugin.

    This class implements a L3 service plugin that provides
    router and floatingip resources and manages associated
    request/response.
    """
    supported_extension_aliases = ["router"]

    def __init__(self):
        super(DFL3RouterPlugin, self).__init__()
        nb_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(
                nb_driver_class(),
                use_pubsub=cfg.CONF.df.enable_df_pub_sub,
                is_neutron_server=True)
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
                               db_port=cfg.CONF.df.remote_db_port)

    def get_plugin_type(self):
        return constants.L3_ROUTER_NAT

    def get_plugin_description(self):
        """Returns string description of the plugin."""
        return ("L3 Router Service Plugin for basic L3 forwarding "
                "using Dragonflow.")

    def create_router(self, context, router):
        with context.session.begin(subtransactions=True):
            router = super(DFL3RouterPlugin, self).create_router(
                context, router)

        router_name = router['id']
        tenant_id = router['tenant_id']
        is_distributed = router.get('distributed', False)
        external_ids = {df_const.DF_ROUTER_NAME_EXT_ID_KEY:
                        router.get('name', 'no_router_name')}
        self.nb_api.create_lrouter(router_name, topic=tenant_id,
                                   external_ids=external_ids,
                                   distributed=is_distributed,
                                   ports=[])
        return router

    def update_router(self, context, router_id, router):
        pass

    def delete_router(self, context, router_id):
        router_name = router_id
        router = self.get_router(context, router_id)
        with context.session.begin(subtransactions=True):
            ret_val = super(DFL3RouterPlugin, self).delete_router(context,
                                                                  router_id)
        try:
            self.nb_api.delete_lrouter(name=router_name,
                                       topic=router['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB, might have "
                      "been deleted concurrently" % router_name)
        return ret_val

    def create_floatingip(self, context, floatingip):
        try:
            floatingip_port = None
            with context.session.begin(subtransactions=True):
                floatingip_dict = super(DFL3RouterPlugin, self).\
                    create_floatingip(
                    context, floatingip,
                    initial_status=const.FLOATINGIP_STATUS_DOWN)

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
                name=floatingip_dict['id'],
                topic=floatingip_dict['tenant_id'],
                floating_ip_address=floatingip_dict['floating_ip_address'],
                floating_network_id=floatingip_dict['floating_network_id'],
                router_id=floatingip_dict['router_id'],
                port_id=floatingip_dict['port_id'],
                fixed_ip_address=floatingip_dict['fixed_ip_address'],
                status=floatingip_dict['status'],
                floating_port_id=floatingip_port['id'],
                floating_mac_address=floatingip_port['mac_address'],
                external_gateway_ip=floatingip_subnet['gateway_ip'],
                external_cidr=floatingip_subnet['cidr'])

        return floatingip_dict

    def update_floatingip(self, context, id, floatingip):
        with context.session.begin(subtransactions=True):
            floatingip_dict = super(DFL3RouterPlugin, self).update_floatingip(
                context, id, floatingip)

        self.nb_api.update_floatingip(
            name=floatingip_dict['id'],
            topic=floatingip_dict['tenant_id'],
            notify=True,
            router_id=floatingip_dict['router_id'],
            port_id=floatingip_dict['port_id'],
            fixed_ip_address=floatingip_dict['fixed_ip_address'],
            status=floatingip_dict['status'])
        return floatingip_dict

    def delete_floatingip(self, context, id):
        with context.session.begin(subtransactions=True):
            floatingip = self.get_floatingip(context, id)
            super(DFL3RouterPlugin, self).delete_floatingip(context, id)

        try:
            self.nb_api.delete_floatingip(name=id,
                                          topic=floatingip['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("floatingip %s is not found in DF DB, might have "
                      "been deleted concurrently" % id)

    def get_floatingip(self, context, id, fields=None):
        with context.session.begin(subtransactions=True):
            fip = super(DFL3RouterPlugin, self).get_floatingip(context, id,
                                                               fields)
            fip['status'] = self.nb_api.get_floatingip(id).status
            return fip

    def add_router_interface(self, context, router_id, interface_info):
        add_by_port, add_by_sub = self._validate_interface_info(
            interface_info)
        if add_by_sub:
            subnet = self.get_subnet(context, interface_info['subnet_id'])
            port = {'port': {'tenant_id': subnet['tenant_id'],
                             'network_id': subnet['network_id'], 'name': '',
                             'admin_state_up': True, 'device_id': '',
                             'device_owner': l3_db.DEVICE_OWNER_ROUTER_INTF,
                             'mac_address': attr.ATTR_NOT_SPECIFIED,
                             'fixed_ips': [{'subnet_id': subnet['id'],
                                            'ip_address':
                                                subnet['gateway_ip']}]}}
            port = self.create_port(context, port)
        elif add_by_port:
            port = self.get_port(context, interface_info['port_id'])
            subnet_id = port['fixed_ips'][0]['subnet_id']
            subnet = self.get_subnet(context, subnet_id)

        lrouter = router_id
        lswitch = subnet['network_id']
        cidr = netaddr.IPNetwork(subnet['cidr'])
        network = "%s/%s" % (port['fixed_ips'][0]['ip_address'],
                             str(cidr.prefixlen))

        logical_port = self.nb_api.get_logical_port(port['id'],
                                                    port['tenant_id'])

        interface_info['port_id'] = port['id']
        if 'subnet_id' in interface_info:
            del interface_info['subnet_id']

        with context.session.begin(subtransactions=True):
            result = super(DFL3RouterPlugin, self).add_router_interface(
                context, router_id, interface_info)

        self.nb_api.add_lrouter_port(port['id'],
                                     lrouter, lswitch,
                                     port['tenant_id'],
                                     mac=port['mac_address'],
                                     network=network,
                                     tunnel_key=logical_port.get_tunnel_key())
        return result

    def remove_router_interface(self, context, router_id, interface_info):
        with context.session.begin(subtransactions=True):
            new_router = super(DFL3RouterPlugin, self).remove_router_interface(
                context, router_id, interface_info)

        subnet = self.get_subnet(context, new_router['subnet_id'])
        network_id = subnet['network_id']

        try:
            self.nb_api.delete_lrouter_port(router_id,
                                            network_id,
                                            subnet['tenant_id'])
        except df_exceptions.DBKeyNotFound:
            LOG.debug("logical router %s is not found in DF DB, "
                      "suppressing delete_lrouter_port "
                      "exception" % router_id)
        return new_router
