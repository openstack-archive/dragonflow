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


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'egress': 'egress_port',
    },
)
class PortPair(mf.ModelBase,
               mixins.BasicEvents,
               mixins.Topic,
               mixins.Name):
    table_name = 'sfc_portpair'

    ingress_port = fields.StringField(required=True)
    egress_port = fields.StringField(required=True)
    correlation_mechanism = df_fields.EnumField(['mpls'])
    weight = fields.FloatField()


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'port_pairs': 'port_pairs',
    },
)
class PortPairGroup(mf.ModelBase,
                    mixins.BasicEvents,
                    mixins.Topic,
                    mixins.Name):
    table_name = 'sfc_portpairgroup'

    port_pairs = df_fields.ReferenceListField(PortPair)


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'source_port_id': 'source_port_id',
        'dest_port_id': 'dest_port_id',
    },
)
class FlowClassifier(mf.ModelBase,
                     mixins.BasicEvents,
                     mixins.Topic,
                     mixins.Name,
                     mixins.UniqueKey):
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
@mf.construct_nb_db_model(
    indexes={
        'flow_classifiers': 'flow_classifiers',
        'port_pair_groups': 'port_pair_groups',
    },
)
class PortChain(mf.ModelBase,
                mixins.BasicEvents,
                mixins.Topic,
                mixins.Name):
    table_name = 'sfc_portchain'

    PROTO_MPLS = 'mpls'

    protocol = df_fields.EnumField([PROTO_MPLS])
    chain_id = fields.IntField()
    port_pair_groups = df_fields.ReferenceListField(PortPairGroup)
    flow_classifiers = df_fields.ReferenceListField(FlowClassifier)
