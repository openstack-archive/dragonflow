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
from neutron_lib.plugins import directory
from neutron_lib.services import base as service_base
from oslo_log import log as logging

from dragonflow.db.models import bgp
from dragonflow.db.neutron import lockedobjects_db as lock_db


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
                  bgp_db.BgpDbMixin):

    supported_extension_aliases = [bgp_ext.BGP_EXT_ALIAS]

    def __init__(self):
        super(DFBgpPlugin, self).__init__()
        self._nb_api = None
        self._register_callbacks()

    @property
    def nb_api(self):
        if self._nb_api is None:
            plugin = directory.get_plugin()
            mech_driver = plugin.mechanism_manager.mech_drivers['df'].obj
            self._nb_api = mech_driver.nb_api

        return self._nb_api

    def get_plugin_name(self):
        return bgp_ext.BGP_EXT_ALIAS + '_svc_plugin'

    def get_plugin_type(self):
        return bgp_ext.BGP_EXT_ALIAS

    def get_plugin_description(self):
        """returns string description of the plugin."""
        return ("BGP dynamic routing service for announcement of next-hops "
                "for private networks and floating IP's host routes.")

    def _register_callbacks(self):
        # TODO(xiaohhui): Add subscribers to router and floatingip changes.
        pass

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
        super(DFBgpPlugin, self).delete_bgp_peer(context, bgp_peer_id)
        self.nb_api.delete(bgp.BGPPeer(id=bgp_peer_id),
                           skip_send_event=True)

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

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def remove_bgp_peer(self, context, bgp_speaker_id, bgp_peer_info):
        ret_value = super(DFBgpPlugin, self).remove_bgp_peer(context,
                                                             bgp_speaker_id,
                                                             bgp_peer_info)
        tenant_id = context.tenant_id
        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=tenant_id))
        bgp_speaker.remove_peer(ret_value['bgp_peer_id'])
        self.nb_api.update(bgp_speaker, skip_send_event=True)
        return ret_value

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def add_gateway_network(self, context, bgp_speaker_id, network_info):
        ret_value = super(DFBgpPlugin, self).add_gateway_network(
            context, bgp_speaker_id, network_info)
        # TODO(xiaohhui): Calculate routes for bgp_speaker_id with network.
        return ret_value

    @lock_db.wrap_db_lock(lock_db.RESOURCE_BGP_SPEAKER)
    def remove_gateway_network(self, context, bgp_speaker_id, network_info):
        ret_value = super(DFBgpPlugin, self).remove_gateway_network(
            context, bgp_speaker_id, network_info)

        tenant_id = context.tenant_id
        self.nb_api.update(bgp.BGPSpeaker(id=bgp_speaker_id,
                                          topic=tenant_id,
                                          routes=[]),
                           skip_send_event=True)

        return ret_value

    def get_advertised_routes(self, context, bgp_speaker_id):
        tenant_id = context.tenant_id
        bgp_speaker = self.nb_api.get(bgp.BGPSpeaker(id=bgp_speaker_id,
                                                     topic=tenant_id))
        return bgp_speaker.routes
