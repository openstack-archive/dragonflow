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

from dragonflow._i18n import _LI
from dragonflow.tests.common import app_testing_objects
from dragonflow.tests.fullstack import test_base

from neutron.agent.common import utils

from oslo_log import log

LOG = log.getLogger(__name__)


class TestApps(test_base.DFTestBase):
    def test_infrastructure(self):
        try:
            topology = app_testing_objects.Topology(self.neutron, self.nb_api)
            subnet1 = topology.create_subnet(cidr='192.168.10.0/24')
            subnet2 = topology.create_subnet(cidr='192.168.11.0/24')
            port1 = subnet1.create_port()
            port2 = subnet2.create_port()
            topology.create_router([subnet1.subnet_id, subnet2.subnet_id])
            LOG.info(_LI('Port1 name: {}').format(port1.tap.tap.name))
            LOG.info(_LI('Port2 name: {}').format(port2.tap.tap.name))
            self._print_command(['ifconfig', '-a'])
            self._print_command(['ovs-vsctl', 'show'], True)
            self._print_command(['ovs-ofctl', 'show', 'br-int'], True)
            self._print_command(['ovs-ofctl', 'dump-flows', 'br-int'], True)
        except Exception:
            try:
                topology.delete()
            except Exception:
                pass  # Ignore
            raise
        topology.delete()

    def _print_command(self, full_args, run_as_root=False):
            LOG.info(_LI('{}').format(utils.execute(
                full_args,
                run_as_root=run_as_root,
                process_input=None,
            )))
