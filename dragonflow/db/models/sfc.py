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
from dragonflow.db.models import l2
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

    ingress_port = df_fields.ReferenceField(l2.LogicalPort)
    egress_port = df_fields.ReferenceField(l2.LogicalPort)
    correlation_mechanism = df_fields.EnumField(['none', 'mpls'])
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
        'source_port': 'source_port',
        'dest_port': 'dest_port',
    },
)
class FlowClassifier(mf.ModelBase,
                     mixins.BasicEvents,
                     mixins.Topic,
                     mixins.Name,
                     mixins.UniqueKey):
    table_name = 'sfc_flowclassifier'

    ether_type = df_fields.EnumField(['IPv4', 'IPv6'])
    protocol = df_fields.EnumField(['TCP', 'UDP'])
    source_cidr = df_fields.IpNetworkField()
    dest_cidr = df_fields.IpNetworkField()
    source_transport_ports = df_fields.PortRangeField()
    dest_transport_ports = df_fields.PortRangeField()

    source_port = df_fields.ReferenceField(l2.LogicalPort)
    dest_port = df_fields.ReferenceField(l2.LogicalPort)
    # TODO(dimak) Add l7 parameters

    @property
    def is_classification_local(self):
        if self.source_port is not None:
            return self.source_port.is_local

        return True

    @property
    def is_dispatch_local(self):
        if self.dest_port is not None:
            return self.dest_port.is_local
        return True


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

    def find_flow_classifier(self, fc_id):
        for fc in self.flow_classifiers:
            if fc.id == fc_id:
                return fc
