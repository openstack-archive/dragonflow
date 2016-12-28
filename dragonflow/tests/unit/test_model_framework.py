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
from jsonmodels import errors
from jsonmodels import fields
import mock
import netaddr

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.tests import base as tests_base
from dragonflow.utils import namespace


class BaseCRUD(object):
    def __init__(self, model):
        pass

    def id(self):
        return self.ID


@mf.register_model
@mf.construct_nb_db_model(nb_crud=BaseCRUD)
class ModelTest(mf.ModelBase):
    table_name = 'table1'


@mf.register_model
@mf.construct_nb_db_model(
    indexes=namespace.Namespace(index1='field1', index2=('field2', 'field3')),
    nb_crud=BaseCRUD,
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
@mf.construct_nb_db_model(events=('event1', 'event2'), nb_crud=BaseCRUD)
class ModelWithEvents(mf.ModelBase):
    pass


@mf.register_model
@mf.construct_nb_db_model(events=('event3',))
class ModelWithMoreEvents(ModelWithEvents):
    pass


class CRUD1(BaseCRUD):
    ID = 1


class CRUD2(BaseCRUD):
    ID = 2


@mf.register_model
@mf.construct_nb_db_model(nb_crud=CRUD1)
class ModelWithNbCrud(mf.ModelBase):
    pass


@mf.register_model
@mf.construct_nb_db_model
class ModelWithInheritedNbCrud(ModelWithNbCrud):
    pass


@mf.register_model
@mf.construct_nb_db_model(nb_crud=CRUD2)
class ModelWithAnotherNbCrud(ModelWithNbCrud):
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
        self.assertEqual(set(('event1', 'event2')),
                         set(ModelWithEvents.get_events()))
        self.assertEqual(set(('event1', 'event2', 'event3')),
                         set(ModelWithMoreEvents.get_events()))

    def test_nb_crud_inheritance(self):
        self.assertEqual(1, ModelWithNbCrud.get_nb_crud().ID)
        self.assertEqual(1, ModelWithInheritedNbCrud.get_nb_crud().ID)
        self.assertEqual(2, ModelWithAnotherNbCrud.get_nb_crud().ID)

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


class ReffedTestModel(mf.ModelBase):
    id = fields.StringField()
    name = fields.StringField()


class FieldTestModel(mf.ModelBase):
    enum = df_fields.EnumField(('a', 'b', 'c'))
    ipaddr = df_fields.IpAddressField()
    ipnetwork = df_fields.IpNetworkField()
    ref = df_fields.ReferenceField(ReffedTestModel)


class TestFields(tests_base.BaseTestCase):
    def test_enum_type(self):
        self.assertRaises(errors.ValidationError,
                          FieldTestModel, enum='d')
        e = FieldTestModel(enum='a')
        self.assertEqual('a', e.to_struct().get('enum'))

    def test_ipaddr(self):
        m = FieldTestModel(ipaddr='1.1.1.1')
        self.assertEqual(netaddr.IPAddress('1.1.1.1'), m.ipaddr)
        self.assertEqual('1.1.1.1', m.to_struct().get('ipaddr'))

    def test_ipnetwork(self):
        m = FieldTestModel(ipnetwork='1.1.1.1/24')
        self.assertEqual(netaddr.IPNetwork('1.1.1.1/24'), m.ipnetwork)
        self.assertEqual('1.1.1.1/24', m.to_struct().get('ipnetwork'))

    def test_ref(self):
        m = FieldTestModel(ref='id1')
        self.assertEqual({'ref': 'id1'}, m.to_struct())
        self.assertEqual('id1', m.ref.id)
        m.ref._fetch_obj = mock.MagicMock(
            return_value=ReffedTestModel(id='id1', name='name1'))
        self.assertEqual('name1', m.ref.name)
