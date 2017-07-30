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
from dragonflow.db.models import mixins


RULE_DIRECTION = ('ingress', 'egress')
RULE_ETHERTYPE = ('IPv4', 'IPv6')


@mf.construct_nb_db_model
class SecurityGroupRule(mf.ModelBase, mixins.BasicEvents, mixins.Topic,
                        mixins.Version):

    direction = df_fields.EnumField(RULE_DIRECTION, required=True)
    ethertype = df_fields.EnumField(RULE_ETHERTYPE, required=True)
    port_range_max = fields.IntField()
    port_range_min = fields.IntField()
    protocol = df_fields.IpProto()
    remote_group_id = fields.StringField()
    remote_ip_prefix = df_fields.IpNetworkField()
    security_group_id = fields.StringField()


@mf.register_model
@mf.construct_nb_db_model
class SecurityGroup(mf.ModelBase, mixins.Topic, mixins.Version, mixins.Name,
                    mixins.BasicEvents, mixins.UniqueKey):

    table_name = "secgroup"
    rules = fields.ListField(SecurityGroupRule)
