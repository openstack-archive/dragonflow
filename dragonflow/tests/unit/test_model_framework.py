# Copyright (c) 2015 OpenStack Foundation.
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
from jsonmodels import fields
import mock

import dragonflow.db.model_framework as mf
from dragonflow.tests import base as tests_base
from dragonflow.utils import namespace


@mf.register_model
@mf.construct_nb_db_model
class ModelTest(mf.ModelBase):
    table_name = 'table1'


@mf.register_model
@mf.construct_nb_db_model(
    indexes=namespace.Namespace(index1='field1', index2=('field2', 'field3')),
)
class ModelTestWithIndexes(mf.ModelBase):
    field1 = fields.StringField()
    field2 = fields.StringField()
    field3 = fields.StringField()


@mf.register_model
@mf.construct_nb_db_model(
    indexes=namespace.Namespace(index1='field2', index3=('field1', 'field3')),
)
class ModelTestWithMoreIndexes(ModelTestWithIndexes):
    pass


@mf.register_model
@mf.construct_nb_db_model(events=('event1', 'event2'))
class ModelWithEvents(mf.ModelBase):
    pass


@mf.register_model
@mf.construct_nb_db_model(events=('event3',))
class ModelWithMoreEvents(ModelWithEvents):
    pass


@mf.construct_nb_db_model(events=('foo', 'bar'))
class EventsMixin(mf.MixinBase):
    pass


@mf.construct_nb_db_model(indexes=namespace.Namespace(foo='foo', bar='bar'))
class IndexesMixin(mf.MixinBase):
    foo = fields.StringField()
    bar = fields.StringField()


@mf.construct_nb_db_model
class ModelWithEventsMixin(ModelWithEvents, EventsMixin):
    pass


@mf.construct_nb_db_model(indexes=namespace.Namespace(foo='bar'))
class ModelWithIndexesMixin(ModelTestWithIndexes, IndexesMixin):
    pass


class TestModelFramework(tests_base.BaseTestCase):
    def test_lookup(self):
        self.assertEqual(ModelTest, mf.get_model('ModelTest'))
        self.assertEqual(ModelTest, mf.get_model('table1'))
        self.assertEqual(ModelTest, mf.get_model(ModelTest))

    def test_indexes_inheritance(self):
        self.assertEqual({'index1': 'field1', 'index2': ('field2', 'field3')},
                         dict(ModelTestWithIndexes.get_indexes()))
        self.assertEqual({'index1': 'field2',
                          'index2': ('field2', 'field3'),
                          'index3': ('field1', 'field3')},
                         dict(ModelTestWithMoreIndexes.get_indexes()))

    def test_events_inheritance(self):
        self.assertItemsEqual(('event1', 'event2'),
                              ModelWithEvents.get_events())
        self.assertItemsEqual(('event1', 'event2', 'event3'),
                              ModelWithMoreEvents.get_events())

    def test_event_register_emit(self):
        event1_cb = mock.MagicMock()
        ModelWithEvents.register_event1(event1_cb)
        ModelWithEvents.emit_event1(True)
        event1_cb.assert_called_once_with(True)

    def test_callbacks_not_shared(self):
        m1 = mock.MagicMock()
        m2 = mock.MagicMock()
        ModelWithEvents.register_event1(m1)
        ModelWithMoreEvents.register_event1(m2)
        ModelWithMoreEvents.emit_event1()

        m1.assert_not_called()
        m2.assert_called()

    def test_register_unregister(self):
        m1 = mock.MagicMock()
        ModelWithEvents.register_event1(m1)
        ModelWithEvents.unregister_event1(m1)
        ModelWithEvents.emit_event1()

        m1.assert_not_called()

    def test_mixin_aggregate_events(self):
        self.assertItemsEqual(('event1', 'event2', 'foo', 'bar'),
                              ModelWithEventsMixin.get_events())

    def test_mixin_aggregate_indexes(self):
        self.assertEqual({'foo': 'bar', 'bar': 'bar', 'index1': 'field1',
                          'index2': ('field2', 'field3')},
                         dict(ModelWithIndexesMixin.get_indexes()))
