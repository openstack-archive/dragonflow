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
from jsonmodels import fields
import testtools
from unittest import mock

from dragonflow.db import api_nb
import dragonflow.db.model_framework as mf
from dragonflow.db.models import mixins
from dragonflow.tests import base as tests_base
from dragonflow.tests.common import utils


@mf.register_model
@mf.construct_nb_db_model
class FieldTestModel(mf.ModelBase, mixins.Version):
    table_name = 'test_mixins'
    field = fields.IntField()


class TestMixinVersions(tests_base.BaseTestCase):
    def setUp(self):
        super(TestMixinVersions, self).setUp()
        self.api_nb = api_nb.NbApi(db_driver=mock.Mock())

    def test_on_create(self):
        instance = FieldTestModel(id='11111111')
        self.api_nb.create(instance, True)
        self.assertEqual(1, instance.version)

    @testtools.skip('review/480194')
    @utils.with_nb_objects(
        FieldTestModel(id='11111111', version=1, field=1)
    )
    def test_on_update(self):
        instance = FieldTestModel(id='11111111', field=2)
        self.api_nb.update(instance, True)
        db_inst = self.api_nb.get(FieldTestModel(id='11111111'))
        self.assertEqual(2, db_inst.version)
