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

from dragonflow.db import models3 as models
from dragonflow.tests import base as tests_base


@models.construct_nb_db_model
class A(models.NbDbModelBase):
    name = fields.StringField()


@models.construct_nb_db_model(events=('extra_event',))
class B(models.NbDbModelWithTopic):
    name = fields.StringField()
    ref_to_a = models.Ref(A)


@models.construct_nb_db_model(events=('extra_event',))
class EagerB(models.NbDbModelWithTopic):
    name = fields.StringField()
    ref_to_a = models.Ref(A, lazy=False)


class TestModels(tests_base.BaseTestCase):

    def test_refs(self):
        with mock.patch('dragonflow.db.models3.db_store'):
            models.db_store.get.return_value = A(id='1', name='A')
            b = B(id='2', topic='1', name='B', ref_to_a='1')
            self.assertEqual('A', b.ref_to_a.name)

    def test_refs_lazyness(self):
        with mock.patch('dragonflow.db.models3.db_store'):
            models.db_store.get.return_value = A(id='1', name='A')
            b = B(id='2', topic='1', name='B', ref_to_a='1')

            self.assertFalse(models.db_store.get.called)
            self.assertEqual('A', b.ref_to_a.name)
            self.assertTrue(models.db_store.get.called)

    def test_refs_eagerness(self):
        with mock.patch('dragonflow.db.models3.db_store'):
            models.db_store.get.return_value = A(id='1', name='A')
            EagerB(id='2', topic='1', name='B', ref_to_a='1')
            self.assertTrue(models.db_store.get.called)

    def test_indexes(self):
        indexes = dict(B.get_indexes())

        self.assertEqual(2, len(indexes))
        self.assertEqual('id', indexes['id'])
        self.assertEqual(('id', 'topic'), indexes['id_topic'])

    def test_events(self):
        self.assertEqual(set(('created', 'updated', 'deleted')),
                         set(A.get_events()))
        self.assertEqual(set(('created', 'updated', 'deleted', 'extra_event')),
                         set(B.get_events()))
