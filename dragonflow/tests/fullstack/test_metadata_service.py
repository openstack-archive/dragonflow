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

from oslo_log import log

from dragonflow.conf import df_metadata_service as df_metadata_service_conf
from dragonflow.tests.fullstack import test_base


LOG = log.getLogger(__name__)


class TestMetadataService(test_base.DFTestBase):

    def setUp(self):
        super(TestMetadataService, self).setUp()
        df_metadata_service_conf.register_opts()

    # TODO(snapiri) Add some tests for the actual metadata service logic
