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
from jsonmodels import errors
from jsonmodels import fields
from neutron_lib import constants

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import l2
from dragonflow.db.models import mixins

CORR_NONE = 'none'
CORR_MPLS = 'mpls'
PROTO_MPLS = 'mpls'


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'egress': 'egress_port.id',
        'ingress': 'ingress_port.id',
    },
)
class PortPair(mf.ModelBase,
               mixins.BasicEvents,
               mixins.Topic,
               mixins.Name):
    table_name = 'sfc_portpair'

    ingress_port = df_fields.ReferenceField(l2.LogicalPort)
    egress_port = df_fields.ReferenceField(l2.LogicalPort)
    correlation_mechanism = df_fields.EnumField([CORR_NONE, CORR_MPLS])
    weight = fields.FloatField()


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'port_pairs': 'port_pairs.id',
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
        'source_port': 'source_port.id',
        'dest_port': 'dest_port.id',
    },
)
class FlowClassifier(mf.ModelBase,
                     mixins.BasicEvents,
                     mixins.Topic,
                     mixins.Name,
                     mixins.UniqueKey):
    table_name = 'sfc_flowclassifier'

    ether_type = df_fields.EnumField(
        [
            constants.IPv4,
            constants.IPv6,
        ],
    )
    protocol = df_fields.EnumField(
        [
            constants.PROTO_NAME_TCP,
            constants.PROTO_NAME_UDP,
        ],
    )
    source_cidr = df_fields.IpNetworkField()
    dest_cidr = df_fields.IpNetworkField()
    source_transport_ports = df_fields.PortRangeField()
    dest_transport_ports = df_fields.PortRangeField()

    source_port = df_fields.ReferenceField(l2.LogicalPort)
    dest_port = df_fields.ReferenceField(l2.LogicalPort)
    # TODO(dimak) Add l7 parameters

    @property
    def is_classification_local(self):
        '''Should the flow classifier classification flows be installed locally

        For classification on source lport, we match using reg6, which is
        available only after classification app sets it, so there is no use
        installing it on other hosts.

        For classification on dest lport, we match using reg7. reg7 is set on
        all hosts during the time packet passes through L2 app. We can classify
        the packet right away on any of the hosts and forward it to the first
        SF, saving 2 hops of going to dest node then to the first SF.
    '''
        if self.source_port is not None:
            return self.source_port.is_local

        return True

    @property
    def is_dispatch_local(self):
        '''Should the flow classifier dispatch flows be installed locally.

        For classification on source lport, we match using reg6, so we can
        dispatch the packet anywhere, and it will be forwarded. No loop will be
        created because no app will set reg6 again.

        For classification on dest lport, we match using reg7, so we have to
        forward the packet all the way to the destination host, and mark it
        as 'already done SFC', so it won't get stuck in a loop. The has to be
        done on the destination host because the mark gets lost in transit.
        '''
        if self.dest_port is not None:
            return self.dest_port.is_local
        return True

    def validate(self):
        '''Make sure exactly one of {source_port, dest_port} is set'''
        super(FlowClassifier, self).validate()
        if self.source_port is None and self.dest_port is None:
            raise errors.ValidationError(
                'One of source_port or dest_port must be set')
        elif self.source_port is not None and self.dest_port is not None:
            raise errors.ValidationError(
                'source_port and dest_port cannot be both set')


@mf.register_model
@mf.construct_nb_db_model(
    indexes={
        'flow_classifiers': 'flow_classifiers.id',
        'port_pair_groups': 'port_pair_groups.id',
    },
)
class PortChain(mf.ModelBase,
                mixins.BasicEvents,
                mixins.Topic,
                mixins.Name):
    table_name = 'sfc_portchain'

    protocol = df_fields.EnumField([PROTO_MPLS])
    chain_id = fields.IntField()
    port_pair_groups = df_fields.ReferenceListField(PortPairGroup)
    flow_classifiers = df_fields.ReferenceListField(FlowClassifier)

    def find_flow_classifier(self, fc_id):
        for fc in self.flow_classifiers:
            if fc.id == fc_id:
                return fc
