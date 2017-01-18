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
from dragonflow.db import models2 as models


@mf.register_model
@mf.construct_nb_db_model
class PortPair(mf.ModelBase,
               models.BasicEventsMixin,
               models.TopicMixin,
               models.NameMixin):
    table_name = 'sfc_portpair'

    ingress_port = fields.StringField(required=True)
    egress_port = fields.StringField(required=True)
    correlation_mechanism = df_fields.EnumField(['mpls', 'nsh'])
    weight = fields.FloatField()


@mf.register_model
@mf.construct_nb_db_model
class PortPairGroup(mf.ModelBase,
                    models.BasicEventsMixin,
                    models.TopicMixin,
                    models.NameMixin):
    table_name = 'sfc_portpairgroup'

    port_pairs = df_fields.ReferenceListField(PortPair)


@mf.register_model
@mf.construct_nb_db_model
class FlowClassifier(mf.ModelBase,
                     models.BasicEventsMixin,
                     models.TopicMixin,
                     models.NameMixin,
                     models.UniqueKeyMixin):
    table_name = 'sfc_flowclassifier'

    ether_type = fields.StringField()
    protocol = fields.StringField()
    source_cidr = df_fields.IpNetworkField()
    dest_cidr = df_fields.IpNetworkField()
    source_transport_ports = df_fields.PortRangeField()
    dest_transport_ports = df_fields.PortRangeField()
    source_port_id = fields.StringField()
    dest_port_id = fields.StringField()
    # l7 parameters


@mf.register_model
@mf.construct_nb_db_model
class PortChain(mf.ModelBase,
                models.BasicEventsMixin,
                models.TopicMixin,
                models.NameMixin):
    table_name = 'sfc_portchain'

    PROTO_MPLS = 'mpls'
    PROTO_NSH = 'nsh'

    protocol = df_fields.EnumField([PROTO_MPLS, PROTO_NSH])
    chain_id = fields.IntField()
    port_pair_groups = df_fields.ReferenceListField(PortPairGroup)
    flow_classifiers = df_fields.ReferenceListField(FlowClassifier)

    def get_mpls_ingress_label(self, fc_idx, hop_idx):
        # FIXME:
        return hop_idx | (fc_idx << 8) | (self.chain_id << 11)

    def get_mpls_egress_label(self, fc_idx, hop_idx):
        return self.get_mpls_ingress_label(fc_idx, hop_idx + 1)
