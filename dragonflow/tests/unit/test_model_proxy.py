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

from dragonflow.db import model_proxy
import dragonflow.db.model_framework as mf
from dragonflow.tests import base as tests_base


class ModelTest(mf.ModelBase):
    id = fields.StringField()
    topic = fields.StringField()


ModelTestProxy = model_proxy.create_model_proxy(ModelTest)


# FIXME add eagerness test and move mocks to db_store/nb_api
class TestObjectProxy(tests_base.BaseTestCase):
    def test_proxied_attrs(self):
        mtp = ModelTestProxy(id='id1')
        mtp._fetch_obj = mock.MagicMock(
            return_value=ModelTest(id='id1', topic='topic1'))
        self.assertEqual('id1', mtp.id)
        self.assertEqual('topic1', mtp.topic)

    def test_lazyness(self):
        mtp = ModelTestProxy(id='id1')
        mtp._fetch_obj = mock.MagicMock(
            return_value=ModelTest(id='id1', topic='topic1'))
        mtp._fetch_obj.assert_not_called()
        self.assertEqual('id1', mtp.id)
        mtp._fetch_obj.assert_not_called()
        self.assertEqual('topic1', mtp.topic)
        mtp._fetch_obj.assert_called()
