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
from jsonmodels import errors
import testtools

from dragonflow.db.models import qos
from dragonflow.tests import base as tests_base


class TestSync(tests_base.BaseTestCase):
    def test_qos_rule_dscp_missing_mark(self):
        with testtools.ExpectedException(errors.ValidationError):
            qos.QosPolicyRule(
                id='qosrule1',
                type=qos.RULE_TYPE_DSCP_MARKING,
            ).validate()

    def test_qos_rule_dscp_hax_mark(self):
        # Check no exception raised
        qos.QosPolicyRule(
            id='qosrule1',
            type=qos.RULE_TYPE_DSCP_MARKING,
            dscp_mark=1,
        ).validate()

    def test_qos_rule_max_bandwidth_missing_rate(self):
        with testtools.ExpectedException(errors.ValidationError):
            qos.QosPolicyRule(
                id='qosrule1',
                type=qos.RULE_TYPE_BANDWIDTH_LIMIT,
            ).validate()

    def test_qos_rule_max_bandwidth_has_rate(self):
        # Check no exception raised
        qos.QosPolicyRule(
            id='qosrule1',
            type=qos.RULE_TYPE_BANDWIDTH_LIMIT,
            max_burst_kbps=1,
        ).validate()
