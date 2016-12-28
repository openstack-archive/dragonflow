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


class ReffedTestModel(mf.ModelBase):
    id = fields.StringField()
    name = fields.StringField()


class FieldTestModel(mf.ModelBase):
    enum = df_fields.EnumField(('a', 'b', 'c'))
    enum_list = df_fields.EnumListField(('a', 'b', 'c'))
    ipaddr = df_fields.IpAddressField()
    ipnetwork = df_fields.IpNetworkField()
    ref = df_fields.ReferenceField(ReffedTestModel)


class TestFields(tests_base.BaseTestCase):
    def test_enum_type(self):
        self.assertRaises(errors.ValidationError,
                          FieldTestModel, enum='d')
        e = FieldTestModel(enum='a')
        self.assertEqual('a', e.to_struct().get('enum'))

    def test_enum_list(self):
        self.assertRaises(errors.ValidationError,
                          FieldTestModel, enum_list=['a', 'b', 'c', 'd'])
        e = FieldTestModel(enum_list=['a', 'b'])
        self.assertEqual(['a', 'b'], e.to_struct().get('enum_list'))
        self.assertEqual(['a', 'b'], e.enum_list)

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
        self.assertEqual('id1', m.to_struct().get('ref'))
        self.assertEqual('id1', m.ref.id)
        m.ref._fetch_obj = mock.MagicMock(
            return_value=ReffedTestModel(id='id1', name='name1'))
        self.assertEqual('name1', m.ref.name)
