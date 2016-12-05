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

import mock

from oslo_serialization import jsonutils

from dragonflow.common import exceptions as df_exceptions
from dragonflow.db import api_nb
from dragonflow.db import models
from dragonflow.tests.unit import test_app_base


class TestNbApiCRUDHelper(test_app_base.DFAppTestBase):
    # This is to comply the current code, as the app_list can't be empty.
    # But we don't need any app in this test, actually.
    apps_list = "l2_app.L2App"

    class DummyModel(models.NbDbObject):
        table_name = 'dummy_table'

    def setUp(self):
        super(TestNbApiCRUDHelper, self).setUp()
        self.dummy_crud = api_nb.NbApi._CRUDHelper(
            self.nb_api,
            self.DummyModel
        )
        self.fakedummy1 = {
            'id': 'fakedummy1',
            'topic': 'faketopic1',
            'extrafield': 'extravalue',
            'collection': [
                {'id': 'subobject1'},
                {'id': 'subobject2'},
            ],
        }
        self.nb_api.driver.get_key.return_value = jsonutils.dumps(
            self.fakedummy1)

    def test_create_db(self):
        self.dummy_crud.create(**self.fakedummy1)
        self.nb_api.driver.create_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            mock.ANY,
            self.fakedummy1['topic'],
        )

        dummy1_json = self.nb_api.driver.create_key.call_args[0][2]
        self.assertEqual(self.fakedummy1, jsonutils.loads(dummy1_json))

    def test_create_pubsub(self):
        self.dummy_crud.create(**self.fakedummy1)
        self.nb_api._send_db_change_event.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            'create',
            mock.ANY,
            self.fakedummy1['topic'],
        )

        dummy1_json = self.nb_api._send_db_change_event.call_args[0][3]
        self.assertEqual(self.fakedummy1, jsonutils.loads(dummy1_json))

    def test_create_pubsub_suppressed(self):
        self.dummy_crud.create(notify=False, **self.fakedummy1)
        self.nb_api._send_db_change_event.assert_not_called()

    def test_update_fetches_from_db(self):
        self.dummy_crud.update(**self.fakedummy1)
        self.nb_api.driver.get_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            self.fakedummy1['topic'],
        )

    def test_update_db(self):
        new_fakedummy1 = self.fakedummy1.copy()
        new_fakedummy1['extra_field'] = 'extravalue'
        full_fakedummy1 = new_fakedummy1.copy()
        del new_fakedummy1['extrafield']

        self.dummy_crud.update(**new_fakedummy1)
        self.nb_api.driver.set_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            mock.ANY,
            self.fakedummy1['topic'],
        )

        dummy1_json = self.nb_api.driver.set_key.call_args[0][2]
        self.assertEqual(full_fakedummy1, jsonutils.loads(dummy1_json))

    def test_update_pubsub(self):
        new_fakedummy1 = self.fakedummy1.copy()
        new_fakedummy1['extra_field'] = 'extravalue'
        full_fakedummy1 = new_fakedummy1.copy()
        del new_fakedummy1['extrafield']

        self.dummy_crud.update(**new_fakedummy1)
        self.nb_api._send_db_change_event.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            'set',
            mock.ANY,
            self.fakedummy1['topic'],
        )

        dummy1_json = self.nb_api._send_db_change_event.call_args[0][3]
        self.assertEqual(full_fakedummy1, jsonutils.loads(dummy1_json))

    def test_update_pubsub_suppressed(self):
        self.dummy_crud.update(notify=False, **self.fakedummy1)
        self.nb_api._send_db_change_event.assert_not_called()

    def test_delete_db(self):
        self.dummy_crud.delete(self.fakedummy1['id'], self.fakedummy1['topic'])
        self.nb_api.driver.delete_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            self.fakedummy1['topic'],
        )

    def test_delete_pubsub(self):
        self.dummy_crud.delete(self.fakedummy1['id'], self.fakedummy1['topic'])
        self.nb_api._send_db_change_event.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            'delete',
            self.fakedummy1['id'],
            self.fakedummy1['topic'],
        )

    def test_delete_raises_when_key_not_in_db(self):
        self.nb_api.driver.delete_key.side_effect = \
            df_exceptions.DBKeyNotFound(key=self.fakedummy1['id'])

        def wrapper():
            self.dummy_crud.delete(self.fakedummy1['id'],
                                   self.fakedummy1['topic'])
        self.assertRaises(df_exceptions.DBKeyNotFound, wrapper)

    def test_get_return_correct_object(self):
        self.assertEqual(self.DummyModel(jsonutils.dumps(self.fakedummy1)),
                         self.dummy_crud.get(self.fakedummy1['id'],
                                             self.fakedummy1['topic']))

    def test_get_queries_db(self):
        self.dummy_crud.get(self.fakedummy1['id'], self.fakedummy1['topic'])
        self.nb_api.driver.get_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            self.fakedummy1['topic'],
        )

    def test_get_returns_none_if_not_found(self):
        self.nb_api.driver.get_key.side_effect = \
            df_exceptions.DBKeyNotFound(key=self.fakedummy1['id'])
        self.assertIsNone(self.dummy_crud.get(self.fakedummy1['id'],
                                              self.fakedummy1['topic']))

    def test_add_element_fetches_only_once(self):
        self.dummy_crud._add_element(self.fakedummy1['id'],
                                     self.fakedummy1['topic'],
                                     1,
                                     'collection',
                                     {'id': 'subobject3'})

        self.nb_api.driver.get_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            self.fakedummy1['topic'],
        )

    def test_add_element_updates(self):
        self.dummy_crud._add_element(self.fakedummy1['id'],
                                     self.fakedummy1['topic'],
                                     1,
                                     'collection',
                                     {'id': 'subobject3'})

        self.nb_api.driver.set_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            mock.ANY,
            self.fakedummy1['topic'],
        )

        submitted_obj = jsonutils.loads(
            self.nb_api.driver.set_key.call_args[0][2])

        self.assertIn({'id': 'subobject3'},
                      submitted_obj['collection'])

    def test_remove_element_fetches_only_once(self):
        self.dummy_crud._remove_element(self.fakedummy1['id'],
                                        self.fakedummy1['topic'],
                                        1,
                                        'collection',
                                        'subobject1')

        self.nb_api.driver.get_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            self.fakedummy1['topic'],
        )

    def test_remove_element_updates(self):
        self.dummy_crud._remove_element(self.fakedummy1['id'],
                                        self.fakedummy1['topic'],
                                        1,
                                        'collection',
                                        'subobject1')

        self.nb_api.driver.set_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            mock.ANY,
            self.fakedummy1['topic'],
        )

        submitted_obj = jsonutils.loads(
            self.nb_api.driver.set_key.call_args[0][2])

        self.assertEqual([{'id': 'subobject2'}], submitted_obj['collection'])

    def test_update_element_fetches_only_once(self):
        self.dummy_crud._update_element(self.fakedummy1['id'],
                                        self.fakedummy1['topic'],
                                        1,
                                        'collection',
                                        'subobject1',
                                        {'a': 'b'})

        self.nb_api.driver.get_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            self.fakedummy1['topic'],
        )

    def test_update_element_updates(self):
        self.dummy_crud._update_element(self.fakedummy1['id'],
                                        self.fakedummy1['topic'],
                                        1,
                                        'collection',
                                        'subobject1',
                                        {'a': 'b'})

        self.nb_api.driver.set_key.assert_called_once_with(
            self.DummyModel.table_name,
            self.fakedummy1['id'],
            mock.ANY,
            self.fakedummy1['topic'],
        )

        submitted_obj = jsonutils.loads(
            self.nb_api.driver.set_key.call_args[0][2])

        self.assertEqual(2, len(submitted_obj['collection']))
        self.assertIn({'id': 'subobject1', 'a': 'b'},
                      submitted_obj['collection'])
        self.assertIn({'id': 'subobject2'}, submitted_obj['collection'])
