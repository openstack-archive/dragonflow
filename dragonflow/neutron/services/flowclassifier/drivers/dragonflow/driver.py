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

from networking_sfc.services.flowclassifier.drivers import base

from dragonflow.db import api_nb
from dragonflow.db import field_types
from dragonflow.db.models import sfc


class _DfFlowClassifierDriverBase(base.FlowClassifierDriverBase):
    def create_flow_classifier(self, context):
        pass

    def update_flow_classifier(self, context):
        pass


class DfFlowClassifierDriver(_DfFlowClassifierDriverBase):
    def initialize(self):
        self.api_nb = api_nb.NbApi.get_instance(True)

    def create_flow_classifier_precommit(self, context):
        pass

    def create_flow_classifier_postcommit(self, context):
        fc = context.current

        protocol = fc.get('protocol')
        if protocol is not None:
            protocol = protocol.upper()

        self.api_nb.create(
            sfc.FlowClassifier(
                id=fc['id'],
                topic=fc['project_id'],
                name=fc.get('name'),
                ether_type=fc.get('ethertype'),
                protocol=protocol,
                source_cidr=fc.get('source_ip_prefix'),
                dest_cidr=fc.get('destination_ip_prefix'),
                source_transport_ports=field_types.PortRange.from_min_max(
                    fc.get('source_port_range_min'),
                    fc.get('source_port_range_max'),
                ),
                dest_transport_ports=field_types.PortRange.from_min_max(
                    fc.get('destination_port_range_min'),
                    fc.get('destination_port_range_max'),
                ),
                source_port=fc.get('logical_source_port'),
                dest_port=fc.get('logical_destination_port'),
                # FIXME (dimak) add support for l7_parameters
            )
        )

    def update_flow_classifier_postcommit(self, context):
        fc = context.current

        # Only name can be updated (and description which we ignore)
        self.api_nb.update(
            sfc.FlowClassifier(
                id=fc['id'],
                topic=fc['project_id'],
                name=fc.get('name'),
            ),
        )

    def delete_flow_classifier(self, context):
        fc = context.current

        self.api_nb.delete(
            sfc.FlowClassifier(
                id=fc['id'],
                topic=fc['project_id'],
            ),
        )
