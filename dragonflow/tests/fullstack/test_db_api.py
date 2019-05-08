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
from dragonflow import conf as cfg
from dragonflow.db import api_nb
from dragonflow.tests.database import test_db_api
from dragonflow.tests.fullstack import test_base


class TestDbApi(test_base.DFTestBase, test_db_api.TestDbApi):

    def setUp(self):
        super(TestDbApi, self).setUp()
        self.driver = df_utils.load_driver(
                cfg.CONF.df.nb_db_class,
                df_utils.DF_NB_DB_DRIVER_NAMESPACE)
        ip, port = api_nb.get_db_ip_port()
        self.driver.initialize(ip, port, config=cfg.CONF.df)
