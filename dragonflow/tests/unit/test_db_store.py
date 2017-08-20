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
from jsonmodels import models
import mock

from dragonflow.db import db_store
from dragonflow.db import field_types as df_fields
from dragonflow.db import model_framework
from dragonflow.db.models import mixins
from dragonflow.tests import base as tests_base


class NestedNestedModel(models.Base):
    name = fields.StringField()


class NestedModel(models.Base):
    submodel2 = fields.EmbeddedField(NestedNestedModel)
    sublist2 = fields.ListField(NestedNestedModel)


@model_framework.construct_nb_db_model
class ReffedModel(model_framework.ModelBase):
    name = fields.StringField()


@model_framework.construct_nb_db_model(
    indexes={
        'id': 'id',
        'topic': 'topic',
        'twicenested': 'submodel1.submodel2.name',
        'refnested': 'ref1.id',
        'listnested': 'sublist1.sublist2.name',
    },
)
class ModelTest(model_framework.ModelBase, mixins.Topic):
    extra_field = fields.StringField()
    submodel1 = fields.EmbeddedField(NestedModel)
    ref1 = df_fields.ReferenceField(ReffedModel)
    sublist1 = fields.ListField(NestedModel)


@model_framework.construct_nb_db_model
class EmbeddedModel(model_framework.ModelBase):
    field = fields.StringField()


@model_framework.construct_nb_db_model
class EmbeddingModel(model_framework.ModelBase):
    field = fields.EmbeddedField(EmbeddedModel)
    list_field = fields.ListField(EmbeddedModel)


class TestDbStore(tests_base.BaseTestCase):
    def setUp(self):
        super(TestDbStore, self).setUp()

        # Skip singleton instance to have clean state for each test
        self.db_store = db_store.DbStore()

    def test_store_retrieve(self):
        o1 = ModelTest(id='id1', topic='topic')

        self.db_store.update(o1)
        self.assertEqual(o1, self.db_store.get_one(ModelTest(id='id1')))
        self.assertIn(o1, self.db_store)
        self.assertIsNone(self.db_store.get_one(ModelTest(id='id2')))

    def test_store_update(self):
        o1 = ModelTest(id='id1', topic='topic')

        self.db_store.update(o1)

        o1_old = o1
        o1 = ModelTest(id='id1', topic='topic', extra_field='foo')
        self.db_store.update(o1)

        self.assertEqual(o1, self.db_store.get_one(ModelTest(id='id1')))

        self.assertIn(o1, self.db_store)
        self.assertNotIn(o1_old, self.db_store)

    def test_store_delete(self):
        o1 = ModelTest(id='id1', topic='topic')
        self.db_store.update(o1)
        self.db_store.delete(o1)
        self.assertNotIn(o1, self.db_store)

    def test_get_all(self):
        o1 = ModelTest(id='id1', topic='topic', extra_field='any1')
        o2 = ModelTest(id='id2', topic='topic', extra_field='any2')

        self.db_store.update(o1)
        self.db_store.update(o2)

        self.assertItemsEqual((o1, o2), self.db_store.get_all(ModelTest))
        self.assertItemsEqual(
            (o1, o2),
            self.db_store.get_all(ModelTest(extra_field=db_store.ANY)),
        )
        self.assertItemsEqual(
            (o1,),
            self.db_store.get_all(
                ModelTest(id='id1'),
                index=ModelTest.get_index('id'),
            ),
        )

    def test_get_all_by_topic(self):
        o1 = ModelTest(id='id1', topic='topic')
        o2 = ModelTest(id='id2', topic='topic1')
        o3 = ModelTest(id='id3', topic='topic')

        self.db_store.update(o1)
        self.db_store.update(o2)
        self.db_store.update(o3)

        self.assertItemsEqual(
            (o1, o3),
            self.db_store.get_all_by_topic(ModelTest, topic='topic'),
        )
        self.assertItemsEqual(
            (o2,),
            self.db_store.get_all_by_topic(ModelTest, topic='topic1'),
        )
        self.assertItemsEqual(
            (o1, o2, o3),
            self.db_store.get_all_by_topic(ModelTest),
        )

    def test_get_keys(self):
        self.db_store.update(ModelTest(id='id1', topic='topic'))
        self.db_store.update(ModelTest(id='id2', topic='topic'))

        self.assertItemsEqual(
            ('id1', 'id2'),
            self.db_store.get_keys(ModelTest),
        )

    def test_get_keys_by_topic(self):
        self.db_store.update(ModelTest(id='id1', topic='topic'))
        self.db_store.update(ModelTest(id='id2', topic='topic1'))
        self.db_store.update(ModelTest(id='id3', topic='topic'))

        self.assertItemsEqual(
            ('id1', 'id3'),
            self.db_store.get_keys_by_topic(ModelTest, topic='topic'),
        )
        self.assertItemsEqual(
            ('id2',),
            self.db_store.get_keys_by_topic(ModelTest, topic='topic1'),
        )
        self.assertItemsEqual(
            ('id1', 'id2', 'id3'),
            self.db_store.get_keys_by_topic(ModelTest),
        )

    def test_key_changed(self):
        mt = ModelTest(id='id1', topic='topic')
        self.db_store.update(mt)
        mt.topic = 'topic2'
        self.db_store.update(mt)
        self.assertItemsEqual(
            ('id1',),
            self.db_store.get_keys_by_topic(ModelTest, topic='topic2'),
        )
        self.assertItemsEqual(
            (),
            self.db_store.get_keys_by_topic(ModelTest, topic='topic'),
        )

    def test_nested_keys(self):
        self.db_store.update(
            ModelTest(
                id='id1',
                topic='topic',
                submodel1=NestedModel(
                    submodel2=NestedNestedModel(
                        name='name1',
                    ),
                ),
            ),
        )
        self.db_store.update(
            ModelTest(
                id='id2',
                topic='topic',
                submodel1=NestedModel(
                    submodel2=NestedNestedModel(
                        name='name2',
                    ),
                ),
            ),
        )

        self.assertItemsEqual(
            ('id1',),
            self.db_store.get_keys(
                ModelTest(
                    submodel1=NestedModel(
                        submodel2=NestedNestedModel(name='name1'),
                    ),
                ),
                index=ModelTest.get_index('twicenested'),
            ),
        )

        self.assertItemsEqual(
            ('id2',),
            self.db_store.get_keys(
                ModelTest(
                    submodel1=NestedModel(
                        submodel2=NestedNestedModel(name='name2'),
                    ),
                ),
                index=ModelTest.get_index('twicenested'),
            ),
        )

    def test_reffed_nested_keys(self):
        with mock.patch(
            'dragonflow.db.db_store.get_instance',
            return_value=self.db_store,
        ):
            self.db_store.update(ReffedModel(id='id1', name='name1'))
            self.db_store.update(ModelTest(id='id2',
                                           topic='topic',
                                           ref1='id1'))
            self.db_store.update(ReffedModel(id='id3', name='name2'))
            self.db_store.update(ModelTest(id='id4',
                                           topic='topic',
                                           ref1='id3'))
            self.assertItemsEqual(
                ('id2',),
                self.db_store.get_keys(
                    ModelTest(ref1=ReffedModel(id='id1')),
                    index=ModelTest.get_index('refnested'),
                ),
            )

    def test_listnested_keys(self):
        self.db_store.update(
            ModelTest(
                id='id1',
                topic='topic',
                sublist1=[
                    NestedModel(
                        sublist2=[
                            NestedNestedModel(name='name1'),
                            NestedNestedModel(name='name2'),
                        ],
                    ),
                    NestedModel(
                        sublist2=[
                            NestedNestedModel(name='name4'),
                            NestedNestedModel(name='name5'),
                        ],
                    ),
                ],
            ),
        )
        self.db_store.update(
            ModelTest(
                id='id2',
                topic='topic',
                sublist1=[
                    NestedModel(
                        sublist2=[
                            NestedNestedModel(name='name3'),
                            NestedNestedModel(name='name4'),
                        ],
                    ),
                ],
            ),
        )
        self.assertItemsEqual(
            ('id1',),
            self.db_store.get_keys(
                ModelTest(
                    sublist1=[
                        NestedModel(
                            sublist2=[
                                NestedNestedModel(name='name1'),
                            ]
                        ),
                    ],
                ),
                index=ModelTest.get_index('listnested'),
            ),
        )

        self.assertItemsEqual(
            ('id2',),
            self.db_store.get_keys(
                ModelTest(
                    sublist1=[
                        NestedModel(
                            sublist2=[
                                NestedNestedModel(name='name3'),
                            ]
                        ),
                    ],
                ),
                index=ModelTest.get_index('listnested'),
            ),
        )

        self.assertItemsEqual(
            ('id1', 'id2',),
            self.db_store.get_keys(
                ModelTest(
                    sublist1=[
                        NestedModel(
                            sublist2=[
                                NestedNestedModel(name='name4'),
                            ]
                        ),
                    ],
                ),
                index=ModelTest.get_index('listnested'),
            ),
        )

        self.assertItemsEqual(
            ('id1', 'id2',),
            self.db_store.get_keys(
                ModelTest(
                    sublist1=[
                        NestedModel(
                            sublist2=[
                                NestedNestedModel(name='name5'),
                                NestedNestedModel(name='name3'),
                            ]
                        ),
                    ],
                ),
                index=ModelTest.get_index('listnested'),
            ),
        )

    def test_store_clear(self):
        o1 = ModelTest(id='id1', topic='topic')
        self.db_store.update(o1)
        self.assertIn(o1, self.db_store)

        self.db_store.clear()
        self.assertNotIn(o1, self.db_store)

    def test_index_nested_objects(self):
        embedded = EmbeddedModel(id='embedded1', field='a')
        embedding = EmbeddingModel(id='embedding1', field=embedded)
        self.db_store.update(embedding)
        self.assertIn(embedded, self.db_store)

    def test_index_list_of_nested_objects(self):
        embedded1 = EmbeddedModel(id='embedded1', field='a')
        embedded2 = EmbeddedModel(id='embedded2', field='b')
        embedding = EmbeddingModel(id='embedding1',
                                   list_field=[embedded1, embedded2])
        self.db_store.update(embedding)
        self.assertIn(embedded1, self.db_store)
        self.assertIn(embedded2, self.db_store)

    def test_delete_nested_objects(self):
        embedded = EmbeddedModel(id='embedded1', field='a')
        embedding = EmbeddingModel(id='embedding1', field=embedded)
        self.db_store.update(embedding)
        self.db_store.delete(embedding)
        self.assertNotIn(embedded, self.db_store)

    def test_delete_list_of_nested_objects(self):
        embedded1 = EmbeddedModel(id='embedded1', field='a')
        embedded2 = EmbeddedModel(id='embedded2', field='b')
        embedding = EmbeddingModel(id='embedding1',
                                   list_field=[embedded1, embedded2])
        self.db_store.update(embedding)
        self.db_store.delete(embedding)
        self.assertNotIn(embedded1, self.db_store)
        self.assertNotIn(embedded2, self.db_store)

    def test_removed_after_change_nested_objects(self):
        embedded = EmbeddedModel(id='embedded1', field='a')
        embedding = EmbeddingModel(id='embedding1', field=embedded)
        self.db_store.update(embedding)
        embedding.field = None
        self.assertIn(embedded, self.db_store)
        self.db_store.update(embedding)
        self.assertNotIn(embedded, self.db_store)

    def test_removed_after_change_list_of_nested_objects(self):
        embedded1 = EmbeddedModel(id='embedded1', field='a')
        embedded2 = EmbeddedModel(id='embedded2', field='b')
        embedding = EmbeddingModel(id='embedding1',
                                   list_field=[embedded1, embedded2])
        self.db_store.update(embedding)
        embedding.list_field = [embedded1]
        self.assertIn(embedded1, self.db_store)
        self.assertIn(embedded2, self.db_store)
        self.db_store.update(embedding)
        self.assertIn(embedded1, self.db_store)
        self.assertNotIn(embedded2, self.db_store)

    def test_nested_object_moves(self):
        embedded = EmbeddedModel(id='embedded1', field='a')
        embedding1 = EmbeddingModel(id='embedding1', field=embedded)
        embedding2 = EmbeddingModel(id='embedding2')
        self.db_store.update(embedding1)
        self.db_store.update(embedding2)
        self.assertIn(embedded, self.db_store)

        embedding1.field = None
        embedding2.field = embedded
        self.assertIn(embedded, self.db_store)

        self.db_store.update(embedding2)
        self.db_store.update(embedding1)
        self.assertIn(embedded, self.db_store)

    def test_mark_object_as_stale(self):
        o1 = ModelTest(id='id1', topic='topic')
        o2 = ModelTest(id='id1', topic='topic', extra_field='test')
        self.db_store.update(o1)
        self.db_store.update(o2)
        self.assertTrue(o1._is_object_stale)

    def test_mark_deleted_object_as_stale(self):
        o1 = ModelTest(id='id1', topic='topic')
        self.db_store.update(o1)
        self.assertFalse(o1._is_object_stale)
        self.db_store.delete(ModelTest(id='id1'))
        self.assertTrue(o1._is_object_stale)
