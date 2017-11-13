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
from dragonflow.common import constants
from dragonflow.db.models import ovs
from dragonflow.ovsdb import impl_idl
from dragonflow.tests import base as tests_base


class TestDFIdl(tests_base.BaseTestCase):
    def setUp(self):
        super(TestDFIdl, self).setUp()

    def test_port_update_qg(self):
        self.assertFalse(
            impl_idl._is_ovsport_update_valid(
                'set',
                ovs.OvsPort(
                    ofport=1,
                    name='qg-some-uuid',
                ),
            ),
        )

    def test_port_update_no_ofport(self):
        self.assertFalse(
            impl_idl._is_ovsport_update_valid(
                'set',
                ovs.OvsPort(
                    name='tap-uuid',
                ),
            ),
        )

    def test_port_update_neg_ofport(self):
        self.assertFalse(
            impl_idl._is_ovsport_update_valid(
                'set',
                ovs.OvsPort(
                    ofport=-1,
                    name='tap-uuid',
                ),
            ),
        )

    def test_port_update_bad_type(self):
        self.assertFalse(
            impl_idl._is_ovsport_update_valid(
                'set',
                ovs.OvsPort(
                    ofport=1,
                    type=constants.OVS_PATCH_INTERFACE,
                    name='tap-uuid',
                ),
            ),
        )

    def test_port_update_missing_lport(self):
        self.assertFalse(
            impl_idl._is_ovsport_update_valid(
                'set',
                ovs.OvsPort(
                    ofport=1,
                    type=constants.OVS_COMPUTE_INTERFACE,
                    name='tap-uuid',
                ),
            ),
        )
