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

from networking_sfc.services.sfc.drivers import base as sfc_driver
from oslo_log import helpers as log_helpers
from oslo_log import log

from dragonflow.db import api_nb
from dragonflow.db.models import sfc_models

LOG = log.getLogger(__name__)


class _DfSfcDriverHiddenBase(sfc_driver.SfcDriverBase):
    def create_port_chain(self, context):
        pass

    def update_port_chain(self, context):
        pass

    def create_port_pair_group(self, context):
        pass

    def update_port_pair_group(self, context):
        pass

    def create_port_pair(self, context):
        pass

    def update_port_pair(self, context):
        pass


class DfSfcDriver(_DfSfcDriverHiddenBase):
    def initialize(self):
        self.api_nb = api_nb.NbApi.get_instance(True)

    @log_helpers.log_method_call
    def create_port_chain_postcommit(self, context):
        pc = context.current
        pc_params = pc.get('chain_parameters')

        self.api_nb.create(
            sfc_models.PortChain(
                id=pc['id'],
                topic=pc['tenant_id'],
                name=pc.get('name'),
                port_pair_groups=list(pc.get('port_pair_groups', [])),
                flow_classifiers=list(pc.get('flow_classifiers', [])),
                protocol=pc_params.get('correlation'),
                chain_id=pc.get('chain_id'),
            ),
        )

    @log_helpers.log_method_call
    def update_port_chain_postcommit(self, context):
        pc = context.current

        self.api_nb.update(
            sfc_models.PortChain(
                id=pc['id'],
                topic=pc['tenant_id'],
                name=pc.get('name'),
                port_pair_groups=list(pc.get('port_pair_groups', [])),
                flow_classifiers=list(pc.get('flow_classifiers', [])),
            ),
        )

    @log_helpers.log_method_call
    def delete_port_chain(self, context):
        pc = context.current

        self.api_nb.delete(
            sfc_models.PortChain(
                id=pc['id'],
                topic=pc['tenant_id'],
            ),
        )

    @log_helpers.log_method_call
    def create_port_pair_group_postcommit(self, context):
        ppg = context.current
        self.api_nb.create(
            sfc_models.PortPairGroup(
                id=ppg['id'],
                topic=ppg['tenant_id'],
                name=ppg.get('name'),
                port_pairs=list(ppg.get('port_pairs', [])),
                # FIXME lb_fields, service_type
            ),
        )

    @log_helpers.log_method_call
    def update_port_pair_group_postcommit(self, context):
        ppg = context.current
        self.api_nb.update(
            sfc_models.PortPairGroup(
                id=ppg['id'],
                topic=ppg['tenant_id'],
                name=ppg.get('name'),
                port_pair_ids=list(ppg.get('port_pairs', [])),
            ),
        )

    @log_helpers.log_method_call
    def delete_port_pair_group(self, context):
        ppg = context.current
        self.api_nb.delete(
            sfc_models.PortPairGroup(
                id=ppg['id'],
                topic=ppg['tenant_id'],
            ),
        )

    @log_helpers.log_method_call
    def create_port_pair_postcommit(self, context):
        pp = context.current
        pp_params = pp.get('port_pair_parameters', {})
        self.api_nb.create(
            sfc_models.PortPair(
                id=pp['id'],
                topic=pp['tenant_id'],
                name=pp.get('name'),
                ingress_port=pp['ingress'],
                egress_port=pp['egress'],
                correlation_mechanism=pp_params.get('correlation'),
                weight=pp_params.get('weight')
            ),
        )

    @log_helpers.log_method_call
    def update_port_pair_postcommit(self, context):
        pp = context.current
        self.api_nb.update(
            sfc_models.PortPair(
                id=pp['id'],
                topic=pp['tenant_id'],
                name=pp.get('name'),
            ),
        )

    @log_helpers.log_method_call
    def delete_port_pair(self, context):
        pp = context.current
        self.api_nb.delete(
            sfc_models.PortPair(
                id=pp['id'],
                topic=pp['tenant_id'],
            ),
        )
