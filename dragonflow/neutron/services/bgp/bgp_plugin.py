# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from neutron_dynamic_routing.db import bgp_db
from neutron_dynamic_routing.extensions import bgp as bgp_ext
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import constants as n_const
from neutron_lib import context as n_context
from neutron_lib.services import base as service_base
from oslo_log import log as logging

from dragonflow.db.models import bgp
from dragonflow.db.models import core
from dragonflow.db.models import l2
from dragonflow.db.neutron import lockedobjects_db as lock_db
from dragonflow.neutron.services import mixins


LOG = logging.getLogger(__name__)


def bgp_peer_from_neutron_bgp_peer(peer):
    return bgp.BGPPeer(id=peer.get('id'),
                       topic=peer.get('tenant_id'),
                       name=peer.get('name'),
                       peer_ip=peer.get('peer_ip'),
                       remote_as=int(peer.get('remote_as')),
                       auth_type=peer.get('auth_type'),
                       password=peer.get('password'))


def bgp_speaker_from_neutron_bgp_speaker(speaker):
    return bgp.BGPSpeaker(id=speaker.get('id'),
                          topic=speaker.get('tenant_id'),
                          name=speaker.get('name'),
                          local_as=int(speaker.get('local_as')),
                          peers=speaker.get('peers', []),
                          ip_version=speaker.get('ip_version'))


class DFBgpPlugin(service_base.ServicePluginBase,
                  bgp_db.BgpDbMixin,
                  mixins.LazyNbApiMixin):

    supported_extension_aliases = [bgp_ext.BGP_EXT_ALIAS]

    def __init__(self):
        super(DFBgpPlugin, self).__init__()
        self._nb_api = None
        self._register_callbacks()

    def get_plugin_name(self):
        return bgp_ext.BGP_EXT_ALIAS + '_svc_plugin'

    def get_plugin_type(self):
        return bgp_ext.BGP_EXT_ALIAS

    def get_plugin_description(self):
        """returns string description of the plugin."""
        return ("BGP dynamic routing service for announcement of next-hops "
                "for private networks and floating IP's host routes.")

    def _register_callbacks(self):
        registry.subscribe(self.floatingip_update_callback,
                           resources.FLOATING_IP,
                           events.AFTER_UPDATE)
        registry.subscribe(self.router_port_callback,
                           resources.ROUTER_INTERFACE,
                           events.AFTER_CREATE)
        registry.subscribe(self.router_port_callback,
                           resources.ROUTER_INTERFACE,
                           events.AFTER_DELETE)
        registry.subscribe(self.router_port_callback,
                           resources.ROUTER_GATEWAY,
                           events.AFTER_CREATE)
        registry.subscribe(self.router_port_callback,
                           resources.ROUTER_GATEWAY,
                           events.AFTER_DELETE)

    def floatingip_update_callback(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        port_id = kwargs['fixed_port_id']
        floating_ip_address = kwargs['floating_ip_address']
        dest = floating_ip_address + '/32'

        if port_id:
            # Associate floatingip
            external_ip = self._get_external_ip_of_lport(port_id,
                                                         context.tenant_id)
            if not external_ip:
                return

            fip_data = {'destination': dest, 'nexthop': external_ip}
            fip_handler = self._add_bgp_speaker_fip_route
        else:
            # Disassociate floatingip
            fip_data = dest
            fip_handler = self._del_bgp_speaker_fip_route

        admin_ctx = n_context.get_admin_context()
        bgp_speakers = self._bgp_speakers_for_gw_network_by_family(
            admin_ctx,
            kwargs['floating_network_id'],
            n_const.IP_VERSION_4)
        for speaker in bgp_speakers:
            fip_handler(context, speaker.id, speaker.project_id, fip_data)

    def _get_external_ip_of_lport(self, lport_id, topic):
        """Get the accessible external ip of chassis where lport resides in"""

        lport = self.nb_api.get(l2.LogicalPort(id=lport_id, topic=topic))
        binding = lport.binding
        if not binding:
            LOG.warning(
                'Logical port %s has not been bound to any host yet', lport_id)
            return

        if binding.type == l2.BINDING_VTEP:
            return binding.vtep_address
        elif binding.type == l2.BINDING_CHASSIS:
            return self._get_external_ip_by_host(binding.chassis.id)

    def _get_external_ip_by_host(self, host):
        chassis = self.nb_api.get(core.Chassis(id=host))
        if not chassis:
            LOG.warning('Unable to find chassis %s', host)
            return

        # If chassis's external_host_ip is not specified,
        # fall back to chassis's ip. This is based on the assumption
        # that they are routable to each other.
        return chassis.external_host_ip or chassis.ip

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def _add_bgp_speaker_fip_route(self, context,
                                   bgp_speaker_id, topic, route):
        """Add host route to bgp speaker in nb db"""

        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=topic))
        # Since all routable cidrs are in one address scope, they should be
        # unique in such context.
        current_routes = {str(r.destination): r
                          for r in bgp_speaker.host_routes}
        cidr = route['destination']
        if (cidr in current_routes and
                route == current_routes[cidr].to_struct()):
            # Nothing changes, skip.
            return

        current_routes[cidr] = route
        bgp_speaker.host_routes = current_routes.values()
        self.nb_api.update(bgp_speaker, skip_send_event=True)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def _del_bgp_speaker_fip_route(self, context, bgp_speaker_id, topic, cidr):
        """Delete host route from bgp speaker in nd db"""

        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=topic))
        current_routes = {str(r.destination): r
                          for r in bgp_speaker.host_routes}
        if cidr not in current_routes:
            # Route has not been added, skip.
            return

        del current_routes[cidr]
        bgp_speaker.host_routes = current_routes.values()
        self.nb_api.update(bgp_speaker, skip_send_event=True)

    def router_port_callback(self, resource, event, trigger, **kwargs):
        gw_network = kwargs['network_id']
        # NOTE(xiaohhui) Not all events have context in kwargs(e.g router
        # gw after create event), just get a admin context here.
        admin_ctx = n_context.get_admin_context()
        speakers = self._bgp_speakers_for_gateway_network(admin_ctx,
                                                          gw_network)

        for speaker in speakers:
            self._update_bgp_speaker_tenant_network_routes(admin_ctx,
                                                           speaker.id,
                                                           speaker.project_id)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def _update_bgp_speaker_tenant_network_routes(self, context,
                                                  bgp_speaker_id, topic):
        """Update the prefix routes while keep the host(fip) routes"""

        prefixes = self._get_tenant_network_routes_by_bgp_speaker(
            context, bgp_speaker_id)
        # Translate to the format of dragonflow db data.
        routes = [{'destination': x['destination'],
                   'nexthop': x['next_hop']} for x in prefixes]
        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=topic))

        bgp_speaker.prefix_routes = routes
        self.nb_api.update(bgp_speaker, skip_send_event=True)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_bgp_speaker(self, context, bgp_speaker):
        bgp_speaker = super(DFBgpPlugin, self).create_bgp_speaker(context,
                                                                  bgp_speaker)
        self.nb_api.create(bgp_speaker_from_neutron_bgp_speaker(bgp_speaker),
                           skip_send_event=True)
        return bgp_speaker

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def update_bgp_speaker(self, context, bgp_speaker_id, bgp_speaker):
        bgp_speaker = super(DFBgpPlugin, self).update_bgp_speaker(
            context, bgp_speaker_id, bgp_speaker)
        self.nb_api.update(bgp_speaker_from_neutron_bgp_speaker(bgp_speaker),
                           skip_send_event=True)
        return bgp_speaker

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def delete_bgp_speaker(self, context, bgp_speaker_id):
        super(DFBgpPlugin, self).delete_bgp_speaker(context, bgp_speaker_id)
        self.nb_api.delete(bgp.BGPSpeaker(id=bgp_speaker_id),
                           skip_send_event=True)

    @lock_db.wrap_db_lock(lock_db.RESOURCE_DF_PLUGIN)
    def create_bgp_peer(self, context, bgp_peer):
        bgp_peer = super(DFBgpPlugin, self).create_bgp_peer(context, bgp_peer)
        self.nb_api.create(bgp_peer_from_neutron_bgp_peer(bgp_peer),
                           skip_send_event=True)
        return bgp_peer

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_PEER)
    def update_bgp_peer(self, context, bgp_peer_id, bgp_peer):
        bgp_peer = super(DFBgpPlugin, self).update_bgp_peer(context,
                                                            bgp_peer_id,
                                                            bgp_peer)
        self.nb_api.update(bgp_peer_from_neutron_bgp_peer(bgp_peer),
                           skip_send_event=True)
        return bgp_peer

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_PEER)
    def delete_bgp_peer(self, context, bgp_peer_id):
        speakers = self._get_bgp_speakers_by_bgp_peer(context, bgp_peer_id)
        super(DFBgpPlugin, self).delete_bgp_peer(context, bgp_peer_id)
        self.nb_api.delete(bgp.BGPPeer(id=bgp_peer_id),
                           skip_send_event=True)

        for s in speakers:
            self._remove_bgp_peer_from_bgp_speaker(context, s['id'],
                                                   bgp_peer_id, s['tenant_id'])

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def add_bgp_peer(self, context, bgp_speaker_id, bgp_peer_info):
        ret_value = super(DFBgpPlugin, self).add_bgp_peer(context,
                                                          bgp_speaker_id,
                                                          bgp_peer_info)
        tenant_id = context.tenant_id
        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=tenant_id))
        bgp_speaker.peers.append(ret_value['bgp_peer_id'])
        self.nb_api.update(bgp_speaker, skip_send_event=True)
        return ret_value

    def remove_bgp_peer(self, context, bgp_speaker_id, bgp_peer_info):
        ret_value = super(DFBgpPlugin, self).remove_bgp_peer(context,
                                                             bgp_speaker_id,
                                                             bgp_peer_info)
        tenant_id = context.tenant_id
        self._remove_bgp_peer_from_bgp_speaker(context,
                                               bgp_speaker_id,
                                               ret_value['bgp_peer_id'],
                                               tenant_id)
        return ret_value

    def add_gateway_network(self, context, bgp_speaker_id, network_info):
        ret_value = super(DFBgpPlugin, self).add_gateway_network(
            context, bgp_speaker_id, network_info)

        tenant_id = context.tenant_id
        self._update_bgp_speaker_routes(context,
                                        bgp_speaker_id,
                                        tenant_id)
        return ret_value

    def remove_gateway_network(self, context, bgp_speaker_id, network_info):
        ret_value = super(DFBgpPlugin, self).remove_gateway_network(
            context, bgp_speaker_id, network_info)

        tenant_id = context.tenant_id
        self._update_bgp_speaker_routes(context,
                                        bgp_speaker_id,
                                        tenant_id)
        return ret_value

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def _update_bgp_speaker_routes(self, context, bgp_speaker_id, topic):
        """Update the all routes of bgp speaker"""

        prefixes = self._get_tenant_network_routes_by_bgp_speaker(
            context, bgp_speaker_id)
        # Translate to the format of dragonflow db data.
        prefix_routes = [{'destination': x['destination'],
                          'nexthop': x['next_hop']} for x in prefixes]

        host_routes = []
        for _net_id, host, addr in self._get_fip_query(
                                       context, bgp_speaker_id).all():
            external_ip = self._get_external_ip_by_host(host)
            if not external_ip:
                continue

            host_routes.append({'destination': addr + '/32',
                                'nexthop': external_ip})

        lean_bgp_speaker = bgp.BGPSpeaker(id=bgp_speaker_id,
                                          topic=topic,
                                          prefix_routes=prefix_routes,
                                          host_routes=host_routes)
        self.nb_api.update(lean_bgp_speaker, skip_send_event=True)

    def _get_bgp_speakers_by_bgp_peer(self, context, bgp_peer_id):
        bgp_binding = bgp_db.BgpSpeakerPeerBinding
        filters = [bgp_binding.bgp_speaker_id == bgp_db.BgpSpeaker.id,
                   bgp_binding.bgp_peer_id == bgp_peer_id]
        with context.session.begin(subtransactions=True):
            query = context.session.query(bgp_db.BgpSpeaker)
            query = query.filter(*filters)
            return [{'id': x['id'], 'tenant_id': x['tenant_id']}
                    for x in query.all()]

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def _remove_bgp_peer_from_bgp_speaker(self, context,
                                          bgp_speaker_id, peer_id, topic):
        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=topic))
        bgp_speaker.remove_peer(peer_id)
        self.nb_api.update(bgp_speaker, skip_send_event=True)

    def get_advertised_routes(self, context, bgp_speaker_id):
        tenant_id = context.tenant_id
        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=tenant_id))
        bgp_routes = bgp_speaker.host_routes + bgp_speaker.prefix_routes
        # Translate to the format that neutron will acccept.
        return {'advertised_routes': [{'destination': r.destination,
                                       'next_hop': r.nexthop}
                                      for r in bgp_routes]}
