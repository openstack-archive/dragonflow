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

from oslo_config import cfg

from neutron.agent.linux import ip_lib

from dragonflow.cmd.eventlet import df_metadata_service
from dragonflow.controller import metadata_service_app
from dragonflow.tests.fullstack import test_base


class TestMetadataService(test_base.DFTestBase):

    def setUp(self):
        super(TestMetadataService, self).setUp()
        cfg.CONF.register_opts(metadata_service_app.options,
                               group='df_metadata')
        self.metadata_ip = cfg.CONF.df_metadata.ip

    def test_metadata_proxy_exit_clear_ip_rule(self):
        df_metadata_service.environment_setup()
        ip_rule = ip_lib.IPRule().rule
        rules = ip_rule.list_rules(4)
        rules_source = [r['from'] for r in rules if 'from' in r]
        self.assertIn(self.metadata_ip, rules_source)

        df_metadata_service.environment_destroy()
        rules = ip_rule.list_rules(4)
        rules_source = [r['from'] for r in rules if 'from' in r]
        self.assertNotIn(self.metadata_ip, rules_source)
