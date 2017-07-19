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

from networking_sfc.services.flowclassifier.common import exceptions as fc_exc
from networking_sfc.services.flowclassifier.drivers import base

from dragonflow._i18n import _
from dragonflow.db import field_types
from dragonflow.db.models import sfc
from dragonflow.neutron.services import mixins


class DfFlowClassifierDriver(base.FlowClassifierDriverBase,
                             mixins.LazyNbApiMixin):
    # The new flow classifier driver API:
    def initialize(self):
        pass

    def create_flow_classifier_precommit(self, context):
        flow_classifier = context.current
        source_port = flow_classifier.get('logical_source_port')
        dest_port = flow_classifier.get('logical_destination_port')

        if source_port is None and dest_port is None:
            raise fc_exc.FlowClassifierBadRequest(
                message=_(
                    'Either logical_source_port or logical_destination_port '
                    'have to be specified'
                ),
            )
        if source_port is not None and dest_port is not None:
            raise fc_exc.FlowClassifierBadRequest(
                message=_(
                    'Both logical_source_port and logical_destination_port '
                    'cannot be specified'
                ),
            )

    def create_flow_classifier_postcommit(self, context):
        flow_classifier = context.current

        self.nb_api.create(
            sfc.FlowClassifier(
                id=flow_classifier['id'],
                topic=flow_classifier['project_id'],
                name=flow_classifier.get('name'),
                ether_type=flow_classifier.get('ethertype'),
                protocol=flow_classifier.get('protocol'),
                source_cidr=flow_classifier.get('source_ip_prefix'),
                dest_cidr=flow_classifier.get('destination_ip_prefix'),
                source_transport_ports=field_types.PortRange.from_min_max(
                    flow_classifier.get('source_port_range_min'),
                    flow_classifier.get('source_port_range_max'),
                ),
                dest_transport_ports=field_types.PortRange.from_min_max(
                    flow_classifier.get('destination_port_range_min'),
                    flow_classifier.get('destination_port_range_max'),
                ),
                source_port=flow_classifier.get('logical_source_port'),
                dest_port=flow_classifier.get('logical_destination_port'),
                # FIXME (dimak) add support for l7_parameters
            )
        )

    def update_flow_classifier_postcommit(self, context):
        flow_classifier = context.current

        # Only name can be updated (and description which we ignore)
        self.nb_api.update(
            sfc.FlowClassifier(
                id=flow_classifier['id'],
                topic=flow_classifier['project_id'],
                name=flow_classifier.get('name'),
            ),
        )

    def delete_flow_classifier_postcommit(self, context):
        flow_classifier = context.current

        self.nb_api.delete(
            sfc.FlowClassifier(
                id=flow_classifier['id'],
                topic=flow_classifier['project_id'],
            ),
        )

    # Legacy FC driver API, has to be stubbed due to ABC
    def create_flow_classifier(self, context):
        pass

    def update_flow_classifier(self, context):
        pass

    def delete_flow_classifier(self, context):
        pass
