# Copyright (c) 2015 OpenStack Foundation.
# All Rights Reserved.
#
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

from dragonflow.controller.dnat_app import DNATApp
from dragonflow.tests import base as tests_base
import mock
class TestFloatingIpwithVlan(tests_base.BaseTestCase):

    def setUp(self):
        super(TestFloatingIpwithVlan, self).setUp()
        #self.DNATApp = mock.Mock()
        vswitch_api_mock= mock.Mock()
        nb_api_mock=mock.Mock()
        kwargs = {'vswitch_api':None,'nb_api':None}
        print kwargs['vswitch_api']
        self.DNATApp = DNATApp(api=mock.Mock(),vswitch_api='test_vswitch_api',nb_api='test_nb_api')

    def test_install_network_flows_for_ingress_vlan(self):
        result = self.DNATApp._install_network_flows_for_ingress_vlan('2', '2')
        self.assertEqual(result, None)

    def test_del_network_flows_for_ingress_vlan(self):
        result = self.DNATApp._del_network_flows_for_ingress_vlan('2', '2')
        self.assertEqual(result, None)

    def test_install_network_flows_for_ingress_flat(self):
        result = self.DNATApp._install_network_flows_for_ingress_flat('2')
        self.assertEqual(result, None)

    def test_del_network_flows_for_ingress_flat(self):

        result = self.DNATApp._del_network_flows_for_ingress_flat('2')
        self.assertEqual(result, None)

    def test_install_network_flows_for_ingress_tunnel(self):

        result = self.DNATApp._install_network_flows_for_ingress_tunnel('2','2')
        self.assertEqual(result, None)

    def test_del_network_flows_for_ingress_tunnel(self):

        result = self.DNATApp._del_network_flows_for_ingress_tunnel('2','2')
        self.assertEqual(result, None)