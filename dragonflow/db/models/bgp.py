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

from jsonmodels import fields

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import host_route
from dragonflow.db.models import mixins


# NOTE(xiaohui):
# As both BGPSpeaker and BGPPeer from neutron don't have revision_num now,
# skip adding version to db modles.
@mf.register_model
@mf.construct_nb_db_model
class BGPPeer(mf.ModelBase, mixins.Topic, mixins.Name):
    table_name = "bgp_peer"

    peer_ip = df_fields.IpAddressField(required=True)
    remote_as = fields.IntField(required=True)
    auth_type = fields.StringField()
    password = fields.StringField()


@mf.register_model
@mf.construct_nb_db_model(indexes={'peer_id': 'peers.id'})
class BGPSpeaker(mf.ModelBase, mixins.Topic, mixins.Name):
    table_name = "bgp_speaker"

    local_as = fields.IntField(required=True)
    peers = df_fields.ReferenceListField(BGPPeer)
    host_routes = fields.ListField(host_route.HostRoute)
    prefix_routes = fields.ListField(host_route.HostRoute)
    ip_version = fields.IntField(required=True)

    def remove_peer(self, peer_id):
        self.peers[:] = [peer for peer in self.peers if peer.id != peer_id]
