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
from oslo_log import log

from neutron.agent.common import utils
from neutron.agent.linux import ip_lib

from dragonflow._i18n import _LE
from dragonflow.cmd.eventlet import df_metadata_service
from dragonflow.conf import df_metadata_service as df_metadata_service_conf
from dragonflow.tests.fullstack import test_base


LOG = log.getLogger(__name__)


class TestMetadataService(test_base.DFTestBase):

    def setUp(self):
        super(TestMetadataService, self).setUp()
        df_metadata_service_conf.register_opts()
        # Override defaults to avoid collision with existing metadata service
        cfg.CONF.df_metadata.ip = '1.1.1.1'
        cfg.CONF.df.metadata_interface = 'tap-md-test'
        df_metadata_service.METADATA_ROUTE_TABLE_ID = '3'
        self.metadata_ip = cfg.CONF.df_metadata.ip
        self.isTornDown = False

    def test_metadata_proxy_exit_clear_ip_rule(self):
        df_metadata_service.environment_setup()
        ip_rule = ip_lib.IPRule().rule
        rules = ip_rule.list_rules(4)
        rules_source = [r['from'] for r in rules if 'from' in r]
        self.assertIn(self.metadata_ip, rules_source)

        df_metadata_service.environment_destroy()
        self.isTornDown = True
        rules = ip_rule.list_rules(4)
        rules_source = [r['from'] for r in rules if 'from' in r]
        self.assertNotIn(self.metadata_ip, rules_source)

    def tearDown(self):
        if not self.isTornDown:
            bridge = cfg.CONF.df.integration_bridge
            interface = cfg.CONF.df.metadata_interface
            cmd = ["ovs-vsctl", "del-port", bridge, interface]
            try:
                utils.execute(cmd, run_as_root=True, check_exit_code=[0])
            except Exception:
                LOG.exception(_LE("Failed to delete metadata test port"))

            ip = cfg.CONF.df_metadata.ip
            cmd = ["ip", "rule", "del", "from", ip, "table",
                   df_metadata_service.METADATA_ROUTE_TABLE_ID]
            try:
                utils.execute(cmd, run_as_root=True)
            except Exception:
                LOG.exception(_LE(
                    "Failed to delete metadata test routing rule"
                ))
        super(TestMetadataService, self).tearDown()
