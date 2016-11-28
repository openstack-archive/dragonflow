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

import mock

from dragonflow.tests.unit import test_app_base


class LocalControllerTestCase(test_app_base.DFAppTestBase):

    apps_list = "l2_ml2_app.L2App"

    def test_logical_port_updated(self):
        lport = mock.Mock()
        lport.get_chassis.return_value = "lport-fake-chassis"
        lport.get_id.return_value = "lport-fake-id"
        lport.get_lswitch_id.return_value = "lport-fake-lswitch"
        lport.get_remote_vtep.return_value = False
        self.controller.logical_port_updated(lport)
        lport.set_external_value.assert_not_called()
