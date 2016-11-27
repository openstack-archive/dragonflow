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

from networking_sfc.services.flowclassifier.drivers import base as fc_driver
from oslo_log import helpers as log_helpers
from oslo_log import log

from dragonflow.db import api_nb
from dragonflow.db.models import sfc_models

LOG = log.getLogger(__name__)


class _DfFlowClassifierDriverHiddenBase(fc_driver.FlowClassifierDriverBase):
    def create_flow_classifier(self, context):
        pass

    def update_flow_classifier(self, context):
        pass


class DfFlowClassifierDriver(_DfFlowClassifierDriverHiddenBase):
    def initialize(self):
        self.api_nb = api_nb.NbApi.get_instance(True)

    @log_helpers.log_method_call
    def create_flow_classifier_precommit(self, context):
        pass

    @log_helpers.log_method_call
    def create_flow_classifier_postcommit(self, context):
        fc = context.current

        self.api_nb.create(
            sfc_models.FlowClassifier(
                id=fc['id'],
                topic=fc['tenant_id'],
                name=fc.get('name'),
                ether_type=fc.get('ethertype'),
                protocol=fc.get('protocol'),
                source_cidr=fc.get('source_ip_prefix'),
                dest_cidr=fc.get('destination_ip_prefix'),
                source_transport_ports=_create_port_range(
                    fc.get('source_port_range_min'),
                    fc.get('source_port_range_max'),
                ),
                dest_transport_ports=_create_port_range(
                    fc.get('destination_port_range_min'),
                    fc.get('destination_port_range_max'),
                ),
                source_port_id=fc.get('logical_source_port'),
                dest_port_id=fc.get('logical_destination_port'),
                # l7_parameters=fc.get('l7_parameters'),
            )
        )

    @log_helpers.log_method_call
    def update_flow_classifier_postcommit(self, context):
        fc = context.current

        # Only name can be updated (and description which we ignore)
        self.api_nb.update(
            sfc_models.FlowClassifier(
                id=fc['id'],
                topic=fc['tenant_id'],
                name=fc.get('name'),
            ),
        )

    @log_helpers.log_method_call
    def delete_flow_classifier(self, context):
        fc = context.current

        self.api_nb.delete(
            sfc_models.FlowClassifier(
                id=fc['id'],
                topic=fc['tenant_id'],
            ),
        )


def _create_port_range(port_min, port_max):
    if port_min is not None and port_max is not None:
        return [port_min, port_max]
