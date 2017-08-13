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

from dragonflow.common import exceptions
from dragonflow.db import api_nb
from dragonflow.db import db_common
import dragonflow.db.field_types as df_fields
import dragonflow.db.model_framework as mf
from dragonflow.db.models import mixins
from dragonflow.tests import base as tests_base


@mf.construct_nb_db_model
class ModelTest(mf.ModelBase):
    table_name = 'dummy_table'

    id = fields.StringField()
    topic = fields.StringField()
    field1 = fields.StringField()


@mf.construct_nb_db_model
class TopicModelTest(mf.ModelBase, mixins.Topic):
    table_name = 'topic_model_test'

    field1 = fields.StringField()


class TestNbApi(tests_base.BaseTestCase):
    def setUp(self):
        super(TestNbApi, self).setUp()
        self.api_nb = api_nb.NbApi(
            db_driver=mock.Mock(),
            use_pubsub=True,
            is_neutron_server=True
        )
        self.api_nb.publisher = mock.Mock()
        self.api_nb.enable_selective_topo_dist = True

    def test_topicless_send_event(self):
        self.api_nb._send_db_change_event('table', 'key', 'action',
                                          'value', None)
        self.api_nb.publisher.send_event.assert_called()
        update, = self.api_nb.publisher.send_event.call_args_list[0][0]
        self.assertEqual(db_common.SEND_ALL_TOPIC, update.topic)

    def test_send_event_with_topic(self):
        self.api_nb._send_db_change_event('table', 'key', 'action',
                                          'value', 'topic')
        self.api_nb.publisher.send_event.assert_called()
        update, = self.api_nb.publisher.send_event.call_args_list[0][0]
        self.assertEqual('topic', update.topic)

    def test_create(self):
        m = ModelTest(id='id1', topic='topic')
        m.on_create_pre = mock.Mock()
        self.api_nb.create(m)

        self.api_nb.publisher.send_event.assert_called_once()
        update, = self.api_nb.publisher.send_event.call_args_list[0][0]

        self.assertEqual('dummy_table', update.table)
        self.assertEqual('id1', update.key)
        self.assertEqual('create', update.action)
        self.assertEqual('topic', update.topic)
        self.assertEqual(m.to_json(), update.value)

        self.api_nb.driver.create_key.assert_called_once_with(
            'dummy_table', 'id1', m.to_json(), 'topic')

        m.on_create_pre.assert_called()

    def test_update(self):
        old_m = ModelTest(id='id1', topic='topic', field1='2')
        old_m.on_update_pre = mock.Mock()
        self.api_nb.get = mock.Mock(return_value=old_m)
        m_update = ModelTest(id='id1', field1='1')
        self.api_nb.update(m_update)

        m_new = ModelTest(id='id1', topic='topic', field1='1')

        self.api_nb.publisher.send_event.assert_called_once()
        update, = self.api_nb.publisher.send_event.call_args_list[0][0]

        self.assertEqual('dummy_table', update.table)
        self.assertEqual('id1', update.key)
        self.assertEqual('set', update.action)
        self.assertEqual('topic', update.topic)
        self.assertEqual(m_new.to_json(), update.value)

        self.api_nb.driver.set_key.assert_called_once_with(
            'dummy_table', 'id1', m_new.to_json(), 'topic')

        old_m.on_update_pre.assert_called()

    def test_update_nonexistent(self):
        m = ModelTest(id='id1', topic='topic')
        self.api_nb.driver.get_key.side_effect = exceptions.DBKeyNotFound()
        self.assertRaises(exceptions.DBKeyNotFound, self.api_nb.update, m)

    def test_delete(self):
        m = ModelTest(id='id1', topic='topic')
        m.on_delete_pre = mock.Mock()
        self.api_nb.delete(m)

        self.api_nb.publisher.send_event.assert_called_once()
        update, = self.api_nb.publisher.send_event.call_args_list[0][0]

        self.assertEqual('dummy_table', update.table)
        self.assertEqual('id1', update.key)
        self.assertEqual('delete', update.action)
        self.assertEqual('topic', update.topic)
        self.assertIsNone(update.value)

        self.api_nb.driver.delete_key.assert_called_once_with(
            'dummy_table', 'id1', 'topic')

        m.on_delete_pre.assert_called()

    def test_delete_nonexistent(self):
        m = ModelTest(id='id1', topic='topic')
        self.api_nb.driver.delete_key.side_effect = exceptions.DBKeyNotFound()
        self.assertRaises(exceptions.DBKeyNotFound, self.api_nb.delete, m)

    def test_get(self):
        m = ModelTest(id='id1', topic='topic')
        self.api_nb.driver.get_key.return_value = m.to_json()
        self.assertEqual(m.to_struct(),
                         self.api_nb.get(ModelTest(id='id1')).to_struct())

    def test_get_nonexistent(self):
        self.api_nb.driver.get_key.side_effect = exceptions.DBKeyNotFound()
        self.assertIsNone(self.api_nb.get(ModelTest(id='id1')))

    def test_get_all(self):
        m1 = ModelTest(id='id1', topic='topic')
        m2 = ModelTest(id='id2', topic='topic')
        ModelTest.on_get_all_post = mock.Mock(side_effect=lambda x: x)
        self.api_nb.driver.get_all_entries.return_value = (m1.to_json(),
                                                           m2.to_json())
        res = self.api_nb.get_all(ModelTest)
        self.assertItemsEqual((m1.to_struct(), m2.to_struct()),
                              (o.to_struct() for o in res))
        ModelTest.on_get_all_post.assert_called_once()

    @mock.patch.object(TopicModelTest, 'from_json')
    def test_get_topic(self, from_json):
        self.api_nb.get(TopicModelTest(id='id1'))
        self.api_nb.driver.get_key.assert_called_once_with('topic_model_test',
                                                           'id1', None)
        self.api_nb.driver.get_key.reset_mock()
        self.api_nb.get(TopicModelTest(id='id2', topic='topic1'))
        self.api_nb.driver.get_key.assert_called_once_with('topic_model_test',
                                                           'id2', 'topic1')

    def test_get_on_model_proxy(self):
        @mf.construct_nb_db_model
        class RefferingModel(mf.ModelBase):
            table_name = 'reffering_model_test'
            reffering_field = df_fields.ReferenceField(ModelTest)

        m = RefferingModel(id='id1', reffering_field='id2')
        self.api_nb.driver.get_key.return_value = ModelTest(id='id2').to_json()
        self.api_nb.get(m.reffering_field)
        self.api_nb.driver.get_key.assert_called_once_with('dummy_table',
                                                           'id2', None)
