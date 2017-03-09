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
from dragonflow.db import db_store2
from dragonflow.db import field_types as df_fields
from dragonflow.db import model_framework
from dragonflow.tests import base as tests_base


class TestDbStore(tests_base.BaseTestCase):
    def setUp(self):
        tests_base.BaseTestCase.setUp(self)
        self.db_store = db_store.DbStore()

    def test_port(self):
        port1 = mock.Mock()
        port2 = mock.Mock()
        port2.get_lswitch_id.return_value = 'net1'
        port3 = mock.Mock()
        port3.get_lswitch_id.return_value = 'net1'
        port4 = mock.Mock()
        port4.get_id.return_value = 'port_id3'
        self.db_store.set_port('id1', port1, False, 'topic1')
        self.db_store.set_port('id2', port2, False, 'topic2')
        self.db_store.set_port('id3', port3, False, 'topic2')
        self.db_store.set_port('id4', port4, True, 'topic2')
        port_keys = self.db_store.get_port_keys()
        port_keys_topic2 = self.db_store.get_port_keys('topic2')
        self.assertEqual({'id1', 'id2', 'id3', 'id4'}, set(port_keys))
        self.assertIn('id2', port_keys_topic2)
        self.assertIn('id3', port_keys_topic2)
        ports = self.db_store.get_ports()
        ports_topic2 = self.db_store.get_ports('topic2')
        self.assertEqual({port1, port2, port3, port4}, set(ports))
        self.assertIn(port2, ports_topic2)
        self.assertIn(port3, ports_topic2)
        self.assertEqual(port1, self.db_store.get_port('id1'))
        self.assertEqual(port2, self.db_store.get_port('id2'))
        self.assertEqual(
            port1,
            self.db_store.get_port('id1', 'topic1'),
        )
        self.assertIsNone(self.db_store.get_local_port('id1'))
        self.assertIsNone(self.db_store.get_local_port('id2', 'topic2'))
        self.assertEqual(
            port4,
            self.db_store.get_local_port('id4', 'topic2')
        )
        self.assertEqual(
            port4,
            self.db_store.get_local_port_by_name('tapport_id3')
        )
        self.db_store.delete_port('id4', True, 'topic2')
        self.assertIsNone(
            self.db_store.get_local_port('id4', 'topic2')
        )
        self.assertIsNone(
            self.db_store.get_port('id4', 'topic2')
        )
        self.assertEqual(
            {port2, port3},
            set(self.db_store.get_ports_by_network_id('net1'))
        )
        self.db_store.delete_port('id3', False, 'topic2')
        self.assertIsNone(self.db_store.get_port('id3'))

    def test_router(self):
        router1 = mock.Mock()
        port1_1 = mock.Mock()
        port1_1.get_mac.return_value = '12:34:56:78:90:ab'
        router1.get_ports.return_value = [port1_1]
        router2 = mock.Mock()
        router2.get_ports.return_value = [mock.Mock()]
        router3 = mock.Mock()
        router3.get_ports.return_value = [mock.Mock(), mock.Mock()]
        self.db_store.update_router('id1', router1, 'topic1')
        self.db_store.update_router('id2', router2, 'topic2')
        self.db_store.update_router('id3', router3, 'topic2')
        self.assertEqual(router1, self.db_store.get_router('id1'))
        self.assertEqual(router2, self.db_store.get_router('id2'))
        self.assertEqual(
            router1,
            self.db_store.get_router('id1', 'topic1'),
        )
        self.assertIn(router2, self.db_store.get_routers('topic2'))
        self.assertIn(router3, self.db_store.get_routers('topic2'))
        self.assertEqual(
            {router1, router2, router3},
            set(self.db_store.get_routers()),
        )
        self.assertEqual(
            router1,
            self.db_store.get_router_by_router_interface_mac(
                '12:34:56:78:90:ab'
            )
        )
        self.db_store.delete_router('id3', 'topic2')
        self.assertIsNone(self.db_store.get_router('id3'))

    def test_floating_ip(self):
        fip1 = 'fip1'
        fip2 = 'fip2'
        fip3 = 'fip3'
        self.db_store.update_floatingip('id1', fip1, 'topic1')
        self.db_store.update_floatingip('id2', fip2, 'topic2')
        self.db_store.update_floatingip('id3', fip3, 'topic2')
        self.assertEqual(fip1, self.db_store.get_floatingip('id1'))
        self.assertEqual(fip2, self.db_store.get_floatingip('id2'))
        self.assertEqual(
            fip3,
            self.db_store.get_floatingip('id3', 'topic2')
        )
        fips = self.db_store.get_floatingips()
        fips_topic2 = self.db_store.get_floatingips('topic2')
        self.assertEqual({fip1, fip2, fip3}, set(fips))
        self.assertIn(fip2, fips_topic2)
        self.assertIn(fip3, fips_topic2)
        self.db_store.delete_floatingip('id3', 'topic2')
        self.assertIsNone(self.db_store.get_floatingip('id3', 'topic2'))

    def test_publisher(self):
        pub1 = mock.Mock()
        pub1.get_topic.return_value = None
        pub2 = mock.Mock()
        pub2.get_topic.return_value = None
        pub3 = mock.Mock()
        pub3.get_topic.return_value = None
        self.db_store.update_publisher('id1', pub1)
        self.db_store.update_publisher('id2', pub2)
        self.db_store.update_publisher('id3', pub3)
        self.assertEqual(pub1, self.db_store.get_publisher('id1'))
        self.assertEqual(pub2, self.db_store.get_publisher('id2'))
        self.assertEqual(pub3, self.db_store.get_publisher('id3'))
        self.db_store.delete_publisher('id3')
        self.assertIsNone(self.db_store.get_publisher('id3'))


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
class ModelTest(model_framework.ModelBase):
    id = fields.StringField()
    topic = fields.StringField()
    extra_field = fields.StringField()
    submodel1 = fields.EmbeddedField(NestedModel)
    ref1 = df_fields.ReferenceField(ReffedModel)
    sublist1 = fields.ListField(NestedModel)


class TestDbStore2(tests_base.BaseTestCase):
    def setUp(self):
        super(TestDbStore2, self).setUp()

        # Skip singleton instance to have clean state for each test
        self.db_store = db_store2.DbStore2()

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
        o1 = ModelTest(id='id1', topic='topic')
        o2 = ModelTest(id='id2', topic='topic')

        self.db_store.update(o1)
        self.db_store.update(o2)

        self.assertItemsEqual((o1, o2), self.db_store.get_all(ModelTest))
        self.assertItemsEqual(
            (o1, o2),
            self.db_store.get_all(ModelTest(id=db_store2.ANY)),
        )
        self.assertItemsEqual(
            (o1,),
            self.db_store.get_all(
                ModelTest(id='id1'),
                index=ModelTest.get_indexes()['id'],
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
                index=ModelTest.get_indexes()['twicenested'],
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
                index=ModelTest.get_indexes()['twicenested'],
            ),
        )

    def test_reffed_nested_keys(self):
        with mock.patch(
            'dragonflow.db.db_store2.get_instance',
            return_value=self.db_store,
        ):
            self.db_store.update(ReffedModel(id='id1', name='name1'))
            self.db_store.update(ModelTest(id='id2', ref1='id1'))
            self.db_store.update(ReffedModel(id='id3', name='name2'))
            self.db_store.update(ModelTest(id='id4', ref1='id3'))
            self.assertItemsEqual(
                ('id2',),
                self.db_store.get_keys(
                    ModelTest(ref1=ReffedModel(id='id1')),
                    index=ModelTest.get_indexes()['refnested'],
                ),
            )

    def test_listnested_keys(self):
        self.db_store.update(
            ModelTest(
                id='id1',
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
                index=ModelTest.get_indexes()['listnested'],
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
                index=ModelTest.get_indexes()['listnested'],
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
                index=ModelTest.get_indexes()['listnested'],
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
                index=ModelTest.get_indexes()['listnested'],
            ),
        )
