# Copyright (c) 2016 OpenStack Foundation.
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

from dragonflow.controller import df_db_objects_refresh
from dragonflow.tests import base as tests_base


class TestDbObjectsRefresh(tests_base.BaseTestCase):

    TEST_ITEMS = 8

    def setUp(self):
        super(TestDbObjectsRefresh, self).setUp()
        self.refresher = df_db_objects_refresh.DfObjectRefresher(
            'Mock',
            self._cache_read_ids,
            self._db_read_objects,
            self._cache_update_object,
            self._cache_delete_id)

        self.test_objs = {}
        for _i in range(self.TEST_ITEMS):
            item = mock.Mock()
            self.test_objs[item.get_id()] = item

    def _cache_read_ids(self):
        return self.test_objs.keys()

    def _db_read_objects(self):
        # Return only half of the objects
        objects = list(self.test_objs.values())
        for _idx in range(int(self.TEST_ITEMS / 2)):
            objects.pop()
        return objects

    def _cache_update_object(self, item):
        self.test_objs[item.get_id()] = item

    def _cache_delete_id(self, item_id):
        self.test_objs.pop(item_id, None)

    def test_db_store(self):
        self.refresher.read()
        self.refresher.update()
        self.refresher.delete()
