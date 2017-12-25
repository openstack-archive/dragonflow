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

from testscenarios import load_tests_apply_scenarios as load_tests  # noqa

from dragonflow import conf as cfg
from dragonflow.db.models import trunk as trunk_models
from dragonflow.tests.unit import test_mech_driver


class TestPortBehindPort(test_mech_driver.DFMechanismDriverTestCase):
    scenarios = [
        ('ipvlan', {'segmentation_type': trunk_models.TYPE_IPVLAN}),
        ('macvlan', {'segmentation_type': trunk_models.TYPE_MACVLAN}),
    ]

    def setUp(self):
        cfg.CONF.set_override('auto_detect_port_behind_port',
                              True,
                              group='df')
        super(TestPortBehindPort, self).setUp()

    def test_detect_nested_port(self):
        with self.network() as n,\
             self.subnet(network=n) as s,\
             self.port(subnet=s) as p1,\
             self.port(subnet=s) as p2:
            p1 = p1['port']
            p2 = p2['port']
            p2_ip = p2['fixed_ips'][0]['ip_address']
            aap = {"ip_address": p2_ip}
            if self.segmentation_type == trunk_models.TYPE_MACVLAN:
                aap['mac_address'] = p2['mac_address']
            data = {'port': {'allowed_address_pairs': [aap]}}
            self.nb_api.create.reset_mock()
            req = self.new_update_request(
                    'ports',
                    data, p1['id'])
            req.get_response(self.api)
            cps_id = trunk_models.get_child_port_segmentation_id(
                    p1['id'], p2['id'])
            model = trunk_models.ChildPortSegmentation(
                id=cps_id,
                topic=p1['project_id'],
                parent=p1['id'],
                port=p2['id'],
                segmentation_type=self.segmentation_type,
            )
            self.nb_api.create.assert_called_once_with(model)
