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

from neutron.db import common_db_mixin  # noqa

from dragonflow.common import utils as df_utils
from dragonflow.tests.database import test_db_api


class TestDbApi(test_db_api.TestDbApi):
    def setUp(self):
        super(TestDbApi, self).setUp()
        self.driver = df_utils.load_driver(
                '_dummy_nb_db_driver',
                df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        self.driver.initialize(None, None, config=None)
