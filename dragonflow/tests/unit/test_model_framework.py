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
import contextlib
import copy

from jsonmodels import fields
import mock

from dragonflow.controller import df_base_app
from dragonflow.db import field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import constants
from dragonflow.db.models import mixins
from dragonflow.tests import base as tests_base


@contextlib.contextmanager
def clean_registry():
    with mock.patch.object(mf, '_registered_models', new=set()):
        with mock.patch.object(mf, '_lookup_by_class_name', new={}):
            with mock.patch.object(mf, '_lookup_by_table_name', new={}):
                yield


@mf.register_model
@mf.construct_nb_db_model
class ModelTest(mf.ModelBase, mixins.BasicEvents):
    table_name = 'table1'

    field1 = fields.StringField()
    field2 = fields.StringField()
    field3 = fields.StringField()


@mf.construct_nb_db_model(
    indexes={'index1': 'field1', 'index2': ('field2', 'field3')},
)
class ModelTestWithIndexes(mf.ModelBase):
    field1 = fields.StringField()
    field2 = fields.StringField()
    field3 = fields.StringField()


@mf.construct_nb_db_model(
    indexes={'index1': 'field2', 'index3': ('field1', 'field3')},
)
class ModelTestWithMoreIndexes(ModelTestWithIndexes):
    pass


@mf.construct_nb_db_model(events={'event1', 'event2'})
class ModelWithEvents(mf.ModelBase):
    pass


@mf.construct_nb_db_model(events={'event3'})
class ModelWithMoreEvents(ModelWithEvents):
    pass


@mf.construct_nb_db_model(events={'foo', 'bar'})
class EventsMixin(mf.MixinBase):
    pass


@mf.construct_nb_db_model(indexes={'foo': 'foo', 'bar': 'bar'})
class IndexesMixin(mf.MixinBase):
    foo = fields.StringField()
    bar = fields.StringField()


@mf.construct_nb_db_model
class ModelWithEventsMixin(ModelWithEvents, EventsMixin):
    pass


@mf.construct_nb_db_model(indexes={'foo': 'bar'})
class ModelWithIndexesMixin(ModelTestWithIndexes, IndexesMixin):
    pass


@mf.construct_nb_db_model
class EmbeddingModel(mf.ModelBase):
    field1 = fields.StringField()
    embedded = fields.EmbeddedField(ModelTest)


@mf.register_model
@mf.construct_nb_db_model
class ReffedModel(mf.ModelBase):
    table_name = 'ReffedModel'
    pass


@mf.register_model
@mf.construct_nb_db_model
class ReffingModel(mf.ModelBase):
    table_name = 'ReffingModel'
    ref1 = df_fields.ReferenceField(ReffedModel)


@mf.register_model
@mf.construct_nb_db_model
class ReffingModel2(mf.ModelBase):
    table_name = 'ReffingModel2'
    ref1 = df_fields.ReferenceField(ReffedModel)
    ref2 = df_fields.ReferenceField(ReffingModel)


@mf.register_model
@mf.construct_nb_db_model
class ListReffingModel(mf.ModelBase):
    table_name = 'ListReffingModel'
    ref2 = df_fields.ReferenceListField(ReffingModel)


@mf.construct_nb_db_model
class EmbeddedModel(mf.ModelBase):
    field = fields.StringField()


@mf.construct_nb_db_model
class EmbeddingModel2(mf.ModelBase):
    emb_field = fields.EmbeddedField(EmbeddedModel)
    emb_list = fields.ListField(EmbeddedModel)
    emb_required = fields.EmbeddedField(EmbeddedModel, required=True)


@mf.construct_nb_db_model
class ReffingNonFirstClassModel(mf.ModelBase):
    ref1 = df_fields.ReferenceField(ReffedModel)


@mf.register_model
@mf.construct_nb_db_model
class ReffingModel3(mf.ModelBase):
    table_name = 'ReffingModel3'
    ref = fields.ListField(ReffingNonFirstClassModel)


class TestModelFramework(tests_base.BaseTestCase):
    def test_lookup(self):
        self.assertEqual(ModelTest, mf.get_model('ModelTest'))
        self.assertEqual(ModelTest, mf.get_model('table1'))
        self.assertEqual(ModelTest, mf.get_model(ModelTest))

    def test_indexes_inheritance(self):
        self.assertEqual({'id': ('id',),
                          'index1': ('field1',),
                          'index2': ('field2', 'field3')},
                         ModelTestWithIndexes.get_indexes())
        self.assertEqual({'id': ('id',),
                          'index1': ('field2',),
                          'index2': ('field2', 'field3'),
                          'index3': ('field1', 'field3')},
                         ModelTestWithMoreIndexes.get_indexes())

    def test_events_inheritance(self):
        self.assertItemsEqual(('event1', 'event2'),
                              ModelWithEvents.get_events())
        self.assertItemsEqual(('event1', 'event2', 'event3'),
                              ModelWithMoreEvents.get_events())

    def test_event_register_emit(self):
        event1_cb = mock.MagicMock()
        event2_cb = mock.MagicMock()

        def function1(obj, *args, **kwargs):
            event1_cb(obj, *args, **kwargs)

        def function2(obj, *args, **kwargs):
            event2_cb(obj, *args, **kwargs)

        ModelWithEvents.register_event1(function1)
        ModelWithEvents.register_event2(function2)
        m = ModelWithEvents()
        m.emit_event1(True, kw='a')
        event1_cb.assert_called_once_with(m, True, kw='a')
        event1_cb.reset_mock()
        event2_cb.assert_not_called()
        event2_cb.reset_mock()
        m.emit_event2(True, kw='a')
        event1_cb.assert_not_called()
        event2_cb.assert_called_once_with(m, True, kw='a')

    def test_callbacks_not_shared(self):
        m1 = mock.MagicMock()
        m2 = mock.MagicMock()

        def function1(obj):
            m1()

        def function2(obj):
            m2()

        ModelWithEvents.register_event1(function1)
        ModelWithMoreEvents.register_event1(function2)
        ModelWithMoreEvents().emit_event1()

        m1.assert_not_called()
        m2.assert_called()

    def test_register_unregister(self):
        m1 = mock.MagicMock()
        ModelWithEvents.register_event1(m1)
        ModelWithEvents.unregister_event1(m1)
        ModelWithEvents().emit_event1()

        m1.assert_not_called()

    def test_clear_registered_callbacks(self):
        m1 = mock.MagicMock()
        m1.__name__ = 'mock'
        m1.__module__ = 'mock'
        ModelWithEvents.register_event1(m1)
        ModelWithEvents().emit_event1()
        m1.assert_called_once()
        m1.reset_mock()

        ModelWithEvents.clear_registered_callbacks()
        ModelWithEvents().emit_event1()
        m1.assert_not_called()

    def test_register_as_decorator(self):
        cb = mock.MagicMock()

        @ModelWithEvents.register_event1
        def callback(obj, *args, **kwargs):
            cb(obj, *args, **kwargs)

        m = ModelWithEvents()
        m.emit_event1(1, 2, 3, kw='hello')
        cb.assert_called_with(m, 1, 2, 3, kw='hello')

    def test_mixin_aggregate_events(self):
        self.assertItemsEqual(('event1', 'event2', 'foo', 'bar'),
                              ModelWithEventsMixin.get_events())

    def test_mixin_aggregate_indexes(self):
        self.assertEqual({'foo': ('bar',),
                          'bar': ('bar',),
                          'id': ('id',),
                          'index1': ('field1',),
                          'index2': ('field2', 'field3')},
                         ModelWithIndexesMixin.get_indexes())

    def test_iterate_over_set_fields(self):
        m = ModelTest(field1='a')
        self.assertItemsEqual(('field1',),
                              (n for n, _ in m.iterate_over_set_fields()))
        m.field3 = 'b'
        self.assertItemsEqual(('field1', 'field3'),
                              (n for n, _ in m.iterate_over_set_fields()))

    def test_update(self):
        m = ModelTest(field1='a', field2='b')

        changed_fields = m.update(ModelTest(field3='c'))
        self.assertItemsEqual({'field3'}, changed_fields)
        self.assertItemsEqual(('field1', 'field2', 'field3'),
                              (n for n, _ in m.iterate_over_set_fields()))

        changed_fields = m.update(ModelTest(field2=None))
        self.assertItemsEqual({'field2'}, changed_fields)
        self.assertItemsEqual(('field1', 'field3'),
                              (n for n, _ in m.iterate_over_set_fields()))

    def test_fields_set(self):
        m = ModelTest(field1='a', field2=None)
        self.assertTrue(m.field_is_set('field1'))
        self.assertTrue(m.field_is_set('field2'))
        self.assertFalse(m.field_is_set('field3'))

        del m.field1
        self.assertFalse(m.field_is_set('field1'))
        self.assertTrue(m.field_is_set('field2'))
        self.assertFalse(m.field_is_set('field3'))

        m.field3 = None
        self.assertFalse(m.field_is_set('field1'))
        self.assertTrue(m.field_is_set('field2'))
        self.assertTrue(m.field_is_set('field3'))

    def test_copy(self):
        model_test = ModelTest(id="3", field1='a', field2='b')
        embedding_model_test = EmbeddingModel(id="4", field1='a',
                                              embedded=model_test)
        embedding_model_copy = copy.copy(embedding_model_test)
        self.assertEqual(embedding_model_test, embedding_model_copy)
        self.assertEqual(id(model_test), id(embedding_model_copy.embedded))
        embedding_model_copy.embedded.field3 = 'c'
        self.assertEqual(model_test, embedding_model_copy.embedded)

    def test_deep_copy(self):
        model_test = ModelTest(id="3", field1='a', field2='b')
        embedding_model_test = EmbeddingModel(id="4", field1='a',
                                              embedded=model_test)
        embedding_model_copy = copy.deepcopy(embedding_model_test)
        self.assertEqual(embedding_model_test, embedding_model_copy)
        self.assertNotEqual(id(model_test), id(embedding_model_copy.embedded))
        embedding_model_copy.embedded.field3 = 'c'
        self.assertNotEqual(model_test, embedding_model_copy.embedded)

    def test_model_repr(self):
        instance = ModelTest(id="id", field1="a")
        instance_str = repr(instance)
        self.assertIn(instance_str, {"ModelTest(id='id', field1='a')",
                                     "ModelTest(field1='a', id='id')"})

    def test_app_delayed_register(self):
        m = mock.MagicMock()

        class TestApp(df_base_app.DFlowApp):
            @df_base_app.register_event(ModelTest, constants.EVENT_CREATED)
            def test_created_callback(self, origin, *args, **kwargs):
                m(origin, *args, **kwargs)

        TestApp(
            api=mock.MagicMock(),
            vswitch_api=mock.MagicMock(),
            nb_api=mock.MagicMock(),
        )

        o = ModelTest()
        o.emit_created()
        m.assert_called_once_with(o)

    def test_topological_sort(self):
        sorted_models = mf.iter_models_by_dependency_order(
            first_class_only=False,
        )
        self.assertLess(
            sorted_models.index(ReffedModel),
            sorted_models.index(ReffingModel)
        )
        self.assertLess(
            sorted_models.index(ReffingModel),
            sorted_models.index(ReffingModel2)
        )
        self.assertLess(
            sorted_models.index(ReffingModel),
            sorted_models.index(ListReffingModel)
        )

    def test_loop_detection(self):
        with clean_registry():
            @mf.register_model
            @mf.construct_nb_db_model
            class LoopModel1(mf.ModelBase):
                table_name = '1'
                link = df_fields.ReferenceField('LoopModel2')

            @mf.register_model
            @mf.construct_nb_db_model
            class LoopModel2(mf.ModelBase):
                table_name = '2'
                link = df_fields.ReferenceField('LoopModel3')

            @mf.register_model
            @mf.construct_nb_db_model
            class LoopModel3(mf.ModelBase):
                table_name = '3'
                link = df_fields.ReferenceField(LoopModel1)

            self.assertRaises(
                RuntimeError,
                mf.iter_models_by_dependency_order,
                first_class_only=False,
            )

    def test_loop_detection_with_ref_to_embedded(self):
        with clean_registry():
            @mf.construct_nb_db_model
            class EmbeddedModel(mf.ModelBase):
                pass

            @mf.register_model
            @mf.construct_nb_db_model
            class EmbeddingModel(mf.ModelBase):
                table_name = '1'
                link = fields.EmbeddedField('EmbeddedModel')

            @mf.register_model
            @mf.construct_nb_db_model
            class ReferencingModel(mf.ModelBase):
                table_name = '2'
                link = df_fields.ReferenceField('EmbeddedModel')

            sorted_models = mf.iter_models_by_dependency_order(
                first_class_only=True,
            )
            self.assertItemsEqual([EmbeddingModel, ReferencingModel],
                                  sorted_models)

    def test_invalid_kwargs_init(self):
        self.assertRaises(
            TypeError,
            ModelTest,
            field1='value1',
            field4='value4',
        )

    def test_register_non_first_class(self):
        def create_class():
            @mf.register_model
            @mf.construct_nb_db_model
            class Model1(mf.ModelBase):
                # no table_name
                pass

        with clean_registry():
            self.assertRaises(RuntimeError, create_class)

    def test_register_same_name(self):
        def create_class():
            @mf.register_model
            @mf.construct_nb_db_model
            class Model1(mf.ModelBase):
                table_name = 'a'

        with clean_registry():
            create_class()
            self.assertRaises(RuntimeError, create_class)

    def test_register_same_table(self):
        with clean_registry():
            def create_class():
                @mf.register_model
                @mf.construct_nb_db_model
                class Model2(mf.ModelBase):
                    table_name = 'a'

            @mf.register_model
            @mf.construct_nb_db_model
            class Model1(mf.ModelBase):
                table_name = 'a'

            self.assertRaises(RuntimeError, create_class)

    def test_embedded_model_types(self):
        self.assertItemsEqual(
            [EmbeddedModel],
            EmbeddingModel2.iterate_embedded_model_types(),
        )

    def test_embedded_objects(self):
        emb1 = EmbeddedModel(id='id1', field='1')
        emb2 = EmbeddedModel(id='id2', field='2')
        emb3 = EmbeddedModel(id='id3', field='3')

        embedding1 = EmbeddingModel2(
            emb_field=emb1,
            emb_list=[emb2, emb3],
        )

        self.assertItemsEqual(
            (emb1, emb2, emb3),
            embedding1.iterate_embedded_model_instances(),
        )

    def test_hierarchical_dependency(self):
        sorted_models = mf.iter_models_by_dependency_order()
        self.assertLess(
            sorted_models.index(ReffedModel),
            sorted_models.index(ReffingModel3)
        )
        self.assertIn(ReffedModel, ReffingModel3.dependencies())
