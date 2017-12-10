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

from neutron_lib import constants

from dragonflow import conf as cfg
from dragonflow.db.models import trunk as trunk_models
from dragonflow.tests.unit import test_mech_driver


class TestVIPPortEnabler(test_mech_driver.DFMechanismDriverTestCase):
    def setUp(self):
        cfg.CONF.set_override('auto_enable_vip_ports',
                              True,
                              group='df_loadbalancer')
        super(TestVIPPortEnabler, self).setUp()

    def test_vip_port_enable(self):
        with self.port(device_owner=constants.DEVICE_OWNER_LOADBALANCERV2,
                       admin_state_up=False) as p:
            self.assertEqual(True, p['port']['admin_state_up'])
