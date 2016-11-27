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
from networking_sfc.services.sfc.drivers import base as sfc_driver
from oslo_log import helpers as log_helpers
from oslo_log import log

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
        pass

    @log_helpers.log_method_call
    def create_port_chain_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def update_port_chain_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def delete_port_chain(self, context):
        pass

    @log_helpers.log_method_call
    def create_port_pair_group_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def update_port_pair_group_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def delete_port_pair_group(self, context):
        pass

    @log_helpers.log_method_call
    def create_port_pair_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def update_port_pair_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def delete_port_pair(self, context):
        pass


class _DfFlowClassifierDriverHiddenBase(fc_driver.FlowClassifierDriverBase):
    def create_flow_classifier(self, context):
        pass

    def update_flow_classifier(self, context):
        pass


class DfFlowClassifierDriver(_DfFlowClassifierDriverHiddenBase):
    def initialize(self):
        pass

    @log_helpers.log_method_call
    def create_flow_classifier_precommit(self, context):
        pass

    @log_helpers.log_method_call
    def create_flow_classifier_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def update_flow_classifier_postcommit(self, context):
        pass

    @log_helpers.log_method_call
    def delete_flow_classifier(self, context):
        pass
