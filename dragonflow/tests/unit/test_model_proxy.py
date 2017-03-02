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
import mock

import dragonflow.db.model_framework as mf
from dragonflow.db import model_proxy
from dragonflow.tests import base as tests_base


@mf.construct_nb_db_model
class ModelTest(mf.ModelBase):
    id = fields.StringField()
    topic = fields.StringField()


@mf.construct_nb_db_model
class ModelTest2(mf.ModelBase):
    id = fields.StringField()
    topic = fields.StringField()


ModelTestProxy = model_proxy.create_model_proxy(ModelTest)


class TestObjectProxy(tests_base.BaseTestCase):
    def setUp(self):
        super(TestObjectProxy, self).setUp()
        self.db_store2 = mock.MagicMock()
        self.get_inst_mock = mock.patch(
            'dragonflow.db.db_store2.get_instance',
            return_value=self.db_store2
        )
        self.addCleanup(self.get_inst_mock.stop)
        self.get_inst_mock.start()

    def test_proxied_attrs(self):
        self.db_store2.get_one.return_value = ModelTest(
            id='id1', topic='topic1')

        mtp = ModelTestProxy(id='id1')
        self.assertEqual('id1', mtp.id)
        self.assertEqual('topic1', mtp.topic)
        self.db_store2.get_one.assert_called_once_with(ModelTest(id='id1'))

        self.db_store2.get_one.reset_mock()
        mtp = model_proxy.create_reference(ModelTest, id='id1')
        self.assertEqual('id1', mtp.id)
        self.assertEqual('topic1', mtp.topic)
        self.db_store2.get_one.assert_called_once_with(ModelTest(id='id1'))

    def test_lazyness(self):
        self.db_store2.get_one.return_value = ModelTest(
            id='id1', topic='topic1')

        mtp = ModelTestProxy(id='id1')
        self.assertEqual('id1', mtp.id)
        self.db_store2.get_one.assert_not_called()

        self.assertEqual('topic1', mtp.topic)
        self.db_store2.get_one.assert_called_once_with(ModelTest(id='id1'))

        self.db_store2.get_one.reset_mock()
        mtp = model_proxy.create_reference(ModelTest, id='id1')
        self.assertEqual('id1', mtp.id)
        self.db_store2.get_one.assert_not_called()

        self.assertEqual('topic1', mtp.topic)
        self.db_store2.get_one.assert_called_once_with(ModelTest(id='id1'))

    def test_eagerness(self):
        self.db_store2.get_one.return_value = ModelTest(
            id='id1', topic='topic1')

        ModelTestProxy(id='id1', lazy=False)
        self.db_store2.get_one.assert_called_once_with(ModelTest(id='id1'))

        self.db_store2.get_one.reset_mock()
        model_proxy.create_reference(ModelTest, lazy=False, id='id1')
        self.db_store2.get_one.assert_called_once_with(ModelTest(id='id1'))

    def test_none_reference(self):
        self.assertIsNone(model_proxy.create_reference(ModelTest, id=None))
        self.assertIsNone(model_proxy.create_reference(ModelTest))

    def test_memoization(self):
        self.assertEqual(ModelTestProxy,
                         model_proxy.create_model_proxy(ModelTest))
        self.assertNotEqual(ModelTestProxy,
                            model_proxy.create_model_proxy(ModelTest2))
