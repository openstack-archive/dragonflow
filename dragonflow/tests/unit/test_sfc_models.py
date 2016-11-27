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
from jsonmodels import errors
import testtools

from dragonflow.db.models import sfc
from dragonflow.tests import base as tests_base


class TestSfcModels(tests_base.BaseTestCase):
    def test_flow_classifier_no_ports(self):
        with testtools.ExpectedException(errors.ValidationError):
            sfc.FlowClassifier(
                id='id1',
                topic='topic',
                unique_key=1,
            ).validate()

    def test_flow_classifier_both_ports(self):
        with testtools.ExpectedException(errors.ValidationError):
            sfc.FlowClassifier(
                id='id1',
                topic='topic',
                unique_key=1,
                source_port='port1',
                dest_port='port2',
            ).validate()

    def test_flow_classifier_source_port(self):
        # Check no exception raised
        sfc.FlowClassifier(
            id='id1',
            topic='topic',
            unique_key=1,
            source_port='port1',
        ).validate()

    def test_flow_classifier_dest_port(self):
        # Check no exception raised
        sfc.FlowClassifier(
            id='id1',
            topic='topic',
            unique_key=1,
            dest_port='port1',
        ).validate()
