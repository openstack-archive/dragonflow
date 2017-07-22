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


from neutron.services.l3_router.service_providers import base
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from oslo_log import helpers as log_helpers
from oslo_log import log as logging

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db.models import l2
from dragonflow.db.models import l3
from dragonflow.neutron.common import constants as df_const
from dragonflow.neutron.db.models import l3 as neutron_l3
from dragonflow.neutron.services import mixins


LOG = logging.getLogger(__name__)


def trace(func_name, args):
    LOG.info('dimak2 tracing %s', func_name)

    for key, value in args.items():
        LOG.info('%r: %r', key, value)


@registry.has_registry_receivers
class DfL3ServiceProvider(base.L3ServiceProvider, mixins.LazyNbApiMixin):
    distributed_support = base.OPTIONAL

    def __init__(self, l3_plugin):
        super(DfL3ServiceProvider, self).__init__(l3_plugin)
        self._l3_plugin = l3_plugin

    @registry.receives(resources.ROUTER, [events.AFTER_CREATE])
    @log_helpers.log_method_call
    def _router_after_create(self, resource, event, trigger,
                             router, **kwargs):
        lrouter = neutron_l3.logical_router_from_neutron_router(router)
        self.nb_api.create(lrouter)

    @registry.receives(resources.ROUTER, [events.AFTER_UPDATE])
    @log_helpers.log_method_call
    def _router_after_update(self, resource, event, trigger,
                             router, **kwargs):
        lrouter = neutron_l3.logical_router_from_neutron_router(router)
        try:
            self.nb_api.update(lrouter)
        except df_exceptions.DBKeyNotFound:
            LOG.debug("router %s is not found in DF DB", lrouter.id)

    @registry.receives(resources.ROUTER, [events.AFTER_DELETE])
    @log_helpers.log_method_call
    def _router_after_delete(self, resource, event, trigger,
                             original, **kwargs):
        self.nb_api.delete(
            l3.LogicalRouter(
                id=original['id'],
                topic=original['tenant_id'],
            ),
        )

    @registry.receives(resources.ROUTER_INTERFACE, [events.AFTER_CREATE])
    @log_helpers.log_method_call
    def _add_router_interface(self, resource, event, trigger,
                              context, router_id, port, cidrs, **kwargs):
        router = self._l3_plugin.get_router(context, router_id)

        lrouter = self.nb_api.get(
            l3.LogicalRouter(
                id=router_id,
                topic=router['tenant_id'],
            ),
        )
        lport = self.nb_api.get(
            l2.LogicalPort(
                id=port['id'],
                topic=port['tenant_id'],
            ),
        )
        lrouter.add_router_port(
            l3.LogicalRouterPort(
                id=lport.id,
                topic=lport.topic,
                unique_key=lport.unique_key,
                lswitch=lport.lswitch.id,
                mac=lport.mac,
                network=cidrs[0],
            ),
        )
        lrouter.version = router['revision_number']
        self.nb_api.update(lrouter)

    @registry.receives(resources.ROUTER_INTERFACE, [events.AFTER_DELETE])
    @log_helpers.log_method_call
    def _remove_router_interface(self, resource, event, trigger,
                                 context, router_id, port, **kwargs):
        router = self._l3_plugin.get_router(context, router_id)
        lrouter = self.nb_api.get(
            l3.LogicalRouter(
                id=router_id,
                topic=router['tenant_id'],
            ),
        )
        lrouter.remove_router_port(port['id'])
        lrouter.version = router['revision_number']
        self.nb_api.update(lrouter)

    @registry.receives(resources.FLOATING_IP, [events.AFTER_CREATE])
    @log_helpers.log_method_call
    def _create_floatingip(self, resource, event, trigger, **kwargs):
        trace('fip_create', kwargs)
        pass

    @registry.receives(resources.FLOATING_IP, [events.AFTER_UPDATE])
    @log_helpers.log_method_call
    def _update_floatingip(self, resource, event, trigger, **kwargs):
        trace('fip_update', kwargs)
        fip = kwargs['floating_ip']
        self.nb_api.update(
            l3.FloatingIp(
                id=fip['id'],
                topic=fip['tenant_id'],
                name=fip.get('name', df_const.DF_FIP_DEFAULT_NAME),
                version=fip['revision_number'],
                lrouter=fip['router_id'],
                lport=fip['port_id'],
                fixed_ip_address=fip['fixed_ip_address'],
            ),
        )

    @registry.receives(resources.FLOATING_IP, [events.AFTER_DELETE])
    @log_helpers.log_method_call
    def _delete_floatingip(self, resource, event, trigger, **kwargs):
        trace('fip_delete', kwargs)
        self.nb_api.delete(
            l3.FloatingIp(
                id=kwargs['id'],
                topic=kwargs['tenant_id'],
            ),
        )
