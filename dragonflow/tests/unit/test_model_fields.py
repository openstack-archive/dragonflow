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
import six

import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.tests import base as tests_base


@mf.construct_nb_db_model
class ReffedTestModel(mf.ModelBase):
    name = fields.StringField()


@mf.construct_nb_db_model
class FieldTestModel(mf.ModelBase):
    enum = df_fields.EnumField(('a', 'b', 'c'))
    enum_list = df_fields.EnumListField(('a', 'b', 'c'))
    ipaddr = df_fields.IpAddressField()
    ipnetwork = df_fields.IpNetworkField()
    ref = df_fields.ReferenceField(ReffedTestModel)
    ref_list = df_fields.ReferenceListField(ReffedTestModel)
    ip_list = df_fields.ListOfField(df_fields.IpAddressField())
    port_range = df_fields.PortRangeField()
    dhcp_opts = df_fields.DhcpOptsDictField()

    def __init__(self, **kwargs):
        id = kwargs.pop("id", 'id1')
        super(FieldTestModel, self).__init__(id=id, **kwargs)


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
        m = FieldTestModel(ref='id2')
        self.assertEqual('id2', m.to_struct().get('ref'))
        self.assertEqual('id2', m.ref.id)
        m.ref._fetch_obj = mock.MagicMock(
            return_value=ReffedTestModel(id='id2', name='name1'))
        self.assertEqual('name1', m.ref.name)

    def test_ref_list(self):
        m = FieldTestModel(ref_list=['id1', 'id2'])
        self.assertEqual(['id1', 'id2'], m.to_struct().get('ref_list'))
        self.assertEqual('id1', m.ref_list[0].id)
        self.assertEqual('id2', m.ref_list[1].id)
        m.ref_list[0]._fetch_obj = mock.MagicMock(
            return_value=ReffedTestModel(id='id1', name='name1'))
        self.assertEqual('name1', m.ref_list[0].name)
        m.ref_list[1]._fetch_obj = mock.MagicMock(
            return_value=ReffedTestModel(id='id2', name='name2'))
        self.assertEqual('name2', m.ref_list[1].name)

    def test_list_of_field(self):
        m = FieldTestModel(ip_list=['1.1.1.1', '2.2.2.2'])
        self.assertEqual(netaddr.IPAddress('1.1.1.1'), m.ip_list[0])
        self.assertEqual(netaddr.IPAddress('2.2.2.2'), m.ip_list[1])
        self.assertIsInstance(m.ip_list[0], netaddr.IPAddress)
        self.assertIsInstance(m.ip_list[1], netaddr.IPAddress)
        m_struct = m.to_struct()
        self.assertEqual('1.1.1.1', m_struct['ip_list'][0])
        self.assertEqual('2.2.2.2', m_struct['ip_list'][1])
        self.assertIsInstance(m_struct['ip_list'][0], six.string_types)
        self.assertIsInstance(m_struct['ip_list'][1], six.string_types)

    def test_port_range(self):
        m = FieldTestModel(port_range=[100, 200])
        self.assertEqual([100, 200], m.to_struct().get('port_range'))
        self.assertEqual(100, m.port_range.min)
        self.assertEqual(200, m.port_range.max)

    dhcp_params_good = {
        1: "a",
        2: "b"
    }

    dhcp_params_bad1 = {
        260: "error"
    }

    dhcp_params_bad2 = {
        "error": "error"
    }

    def test_dhcp_parms_fields(self):
        m = FieldTestModel(dhcp_opts=TestFields.dhcp_params_good)
        self.assertEqual("a", m.to_struct().get("dhcp_opts")["1"])
        self.assertEqual("b", m.dhcp_opts[2])
        json = m.to_json()
        parsed = FieldTestModel.from_json(json)
        parsed.validate()

        self.assertRaises(errors.ValidationError, FieldTestModel,
                          dhcp_opts=TestFields.dhcp_params_bad1)

        self.assertRaises(ValueError, FieldTestModel,
                          dhcp_opts=TestFields.dhcp_params_bad2)
