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
import copy
import testtools

from jsonmodels import fields
import mock

from dragonflow.common import exceptions
from dragonflow.db import db_store
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db import model_proxy
from dragonflow.tests import base as tests_base


@mf.construct_nb_db_model
class ModelTest(mf.ModelBase):
    topic = fields.StringField()

    def method(self):
        return 1


@mf.construct_nb_db_model
class ModelTest2(mf.ModelBase):
    topic = fields.StringField()


@mf.construct_nb_db_model
class RefferingModel(mf.ModelBase):
    model_test = df_fields.ReferenceField(ModelTest)
    other_field = fields.StringField()


ModelTestProxy = model_proxy.create_model_proxy(ModelTest)


class TestObjectProxy(tests_base.BaseTestCase):
    def setUp(self):
        super(TestObjectProxy, self).setUp()
        self.db_store = mock.MagicMock()
        self.get_inst_mock = mock.patch(
            'dragonflow.db.db_store.get_instance',
            return_value=self.db_store
        )
        self.addCleanup(self.get_inst_mock.stop)
        self.get_inst_mock.start()

    def test_proxied_objects_equal(self):
        obj1 = RefferingModel(id="id",
                              model_test="model_id",
                              other_field="other")
        obj2 = RefferingModel(id="id",
                              model_test="model_id",
                              other_field="other")
        self.assertEqual(obj1, obj2)

    def test_proxied_attrs(self):
        self.db_store.get_one.return_value = ModelTest(
            id='id1', topic='topic1')

        mtp = ModelTestProxy(id='id1')
        self.assertEqual('id1', mtp.id)
        self.assertEqual('topic1', mtp.topic)
        self.db_store.get_one.assert_called_once_with(ModelTest(id='id1'))

        self.db_store.get_one.reset_mock()
        mtp = model_proxy.create_reference(ModelTest, id='id1')
        self.assertEqual('id1', mtp.id)
        self.assertEqual('topic1', mtp.topic)
        self.db_store.get_one.assert_called_once_with(ModelTest(id='id1'))

    def test_lazyness(self):
        self.db_store.get_one.return_value = ModelTest(
            id='id1', topic='topic1')

        mtp = ModelTestProxy(id='id1')
        self.assertEqual('id1', mtp.id)
        self.db_store.get_one.assert_not_called()

        self.assertEqual('topic1', mtp.topic)
        self.db_store.get_one.assert_called_once_with(ModelTest(id='id1'))

        self.db_store.get_one.reset_mock()
        mtp = model_proxy.create_reference(ModelTest, id='id1')
        self.assertEqual('id1', mtp.id)
        self.db_store.get_one.assert_not_called()

        self.assertEqual('topic1', mtp.topic)
        self.db_store.get_one.assert_called_once_with(ModelTest(id='id1'))

    def test_eagerness(self):
        self.db_store.get_one.return_value = ModelTest(
            id='id1', topic='topic1')

        ModelTestProxy(id='id1', lazy=False)
        self.db_store.get_one.assert_called_once_with(ModelTest(id='id1'))

        self.db_store.get_one.reset_mock()
        model_proxy.create_reference(ModelTest, lazy=False, id='id1')
        self.db_store.get_one.assert_called_once_with(ModelTest(id='id1'))

    def test_none_reference(self):
        self.assertIsNone(model_proxy.create_reference(ModelTest, id=None))
        self.assertIsNone(model_proxy.create_reference(ModelTest))

    def test_memoization(self):
        self.assertEqual(ModelTestProxy,
                         model_proxy.create_model_proxy(ModelTest))
        self.assertNotEqual(ModelTestProxy,
                            model_proxy.create_model_proxy(ModelTest2))

    def test_null_comparison(self):
        # The following test must be assertNotEquals (and not assertIsNotNone)
        # since we test the flow via the __eq__ function. assertIsNotNone tests
        # using 'is', which doesn't use the __eq__ function flow.
        self.assertNotEqual(model_proxy.create_reference(ModelTest, '4321'),
                         None)  # noqa: H203
        m = RefferingModel(other_field='hi there')
        ref = ModelTest(id='1234', topic='3')
        m1 = RefferingModel(model_test=ref)
        m.update(m1)
        self.assertEqual('1234', m.model_test.id)

    def test_proxied_method(self):
        self.db_store.get_one.return_value = ModelTest(
            id='id1', topic='topic1')

        mtp = ModelTestProxy(id='id1')
        self.assertEqual(1, mtp.method())

    def test_is_model_proxy(self):
        model_instance = ModelTest(id='id1', topic='topic1')
        self.assertFalse(model_proxy.is_model_proxy(model_instance))
        model_ref = model_proxy.create_reference(ModelTest, id='id1')
        self.assertTrue(model_proxy.is_model_proxy(model_ref))

    def test_stale_model_refresh(self):
        model_test1 = ModelTest(id='1', topic='topic')
        model_test2 = ModelTest(id='1', topic='topic2')
        self.db_store.get_one.return_value = model_test1
        reffing_model = RefferingModel(id='2', model_test='1')
        reffing_model.model_test.get_object()
        self.db_store.get_one.assert_called_once_with(ModelTest(id='1'))
        self.db_store.get_one.reset_mock()
        self.db_store.get_one.return_value = model_test2
        model_test1._is_object_stale = True
        reffing_model.model_test.get_object()
        self.db_store.get_one.assert_called_once_with(ModelTest(id='1'))

    def test_integration_stale_model_db_store(self):
        db_store_inst = db_store.DbStore()
        with mock.patch('dragonflow.db.db_store.get_instance',
                        return_value=db_store_inst):
            model_test1 = ModelTest(id='1', topic='topic')
            db_store_inst.update(model_test1)
            reffing_model = RefferingModel(id='2', model_test='1')
            self.assertEqual(model_test1,
                             reffing_model.model_test.get_object())
            model_test2 = ModelTest(id='1', topic='topic2')
            db_store_inst.update(model_test2)
            self.assertEqual(model_test2,
                             reffing_model.model_test.get_object())

    def test_model_proxy_copy(self):
        reffing_model = RefferingModel(id='2', model_test='1')
        model_test_ref = reffing_model.model_test
        model_test_ref_copy = copy.copy(model_test_ref)
        model_test_ref_deepcopy = copy.deepcopy(model_test_ref)
        self.assertEqual(model_test_ref, model_test_ref_copy)
        self.assertEqual(model_test_ref, model_test_ref_deepcopy)
        self.assertNotEqual(id(model_test_ref), id(model_test_ref_copy))
        self.assertNotEqual(id(model_test_ref), id(model_test_ref_deepcopy))

    def test_non_existing_reference(self):
        reffing_model = RefferingModel(id='2', model_test='1')
        self.db_store.get_one.return_value = None
        with testtools.ExpectedException(exceptions.ReferencedObjectNotFound):
            topic = reffing_model.model_test.topic  # noqa
