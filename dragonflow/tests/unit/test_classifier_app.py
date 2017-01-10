# Copyright (c) 2016 OpenStack Foundation.
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

#import copy

from dragonflow.controller.common import constants as const
from dragonflow.db import models as db_models
from dragonflow.tests.unit.test_app_base import DFAppTestBase
from dragonflow.tests.unit.test_app_base import make_fake_local_port
from dragonflow.tests.unit.test_app_base import make_fake_logic_switch
import mock


class TestClassifierApp(DFAppTestBase):
    apps_list = "classifier_app.Classifier"

    def setUp(self):
        super(TestClassifierApp, self).setUp()
        fake_vlan_switch1 = make_fake_logic_switch(network_type='vlan',
                id='fake_vlan_switch1', mtu=1500)
        self.controller.update_lswitch(fake_vlan_switch1)
        fake_flat_switch1 = make_fake_logic_switch(network_type='flat',
                id='fake_flat_switch1', mtu=1500)
        self.controller.update_lswitch(fake_flat_switch1)
        self.app = self.open_flow_app.dispatcher.apps[0]

    def test_classifier_for_vlan_port(self):
        fake_local_vlan_port = make_fake_local_port(network_type='vlan',
                lswitch='fake_vlan_switch1')
        network_type = fake_local_vlan_port.get_external_value('network_type')
        print "test network type = %s" % network_type
        self.controller.update_lport(fake_local_vlan_port)
        network_type = fake_local_vlan_port.get_external_value('network_type')
        print "test network type = %s" % network_type
        self.app.mod_flow.assert_called_with(
            datapath=self.app.get_datapath(),
            inst=mock.ANY,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()

    def test_classifier_for_flat_port(self):
        fake_local_vlan_port = make_fake_local_port(network_type='flat',
                lswitch='fake_flat_switch1')
        network_type = fake_local_vlan_port.get_external_value('network_type')
        print "test network type = %s" % network_type
        self.controller.update_lport(fake_local_vlan_port)
        network_type = fake_local_vlan_port.get_external_value('network_type')
        print "test network type = %s" % network_type
        self.app.mod_flow.assert_called_with(
            datapath=self.app.get_datapath(),
            inst=mock.ANY,
            table_id=const.INGRESS_CLASSIFICATION_DISPATCH_TABLE,
            priority=const.PRIORITY_LOW,
            match=mock.ANY)
        self.app.mod_flow.reset_mock()
