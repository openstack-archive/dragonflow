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

import dragonflow.common.helpers as df_helpers
from dragonflow.tests import base as tests_base

from random import randint


def mock_ofport(bridge, local_end, far_end):
    return randint(0, 20)


class Testmappings(tests_base.BaseTestCase):
    def test_ofport_consistency(self):
        bridge1 = 'br-int'
        bridge2 = 'br-ex'
        mapping1 = df_helpers.generate_mapping(bridge1, bridge2, mock_ofport)
        bridge1_patch = 'br-int-patch'
        bridge2_patch = 'br-ex-patch'
        mapping2 = df_helpers.generate_mapping(bridge2,
                                               bridge1,
                                               mock_ofport,
                                               bridge1_patch,
                                               bridge2_patch)
        self.assertEqual(mapping1[bridge1], mapping2[bridge1])
        self.assertEqual(mapping1[bridge2], mapping2[bridge2])
