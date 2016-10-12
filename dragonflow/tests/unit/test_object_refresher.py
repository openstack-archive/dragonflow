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
    ITEMS_TO_DELETE = int(TEST_ITEMS / 2)

    def setUp(self):
        super(TestDbObjectsRefresh, self).setUp()

        self.test_objs = {}
        self.deleted_objs = set()
        for _i in range(self.TEST_ITEMS):
            item = mock.Mock()
            self.test_objs[item.get_id()] = item

    def _db_read_objects(self, topic=None):
        # Return only half of the objects
        objects = list(self.test_objs.values())
        for _idx in range(self.ITEMS_TO_DELETE):
            objects.pop()
        return objects

    def _cache_update_object(self, item):
        self.test_objs[item.get_id()] = item

    def _cache_delete_id(self, item_id):
        self.test_objs.pop(item_id, None)
        self.deleted_objs.add(item_id)

    def test_db_store(self):
        refresher = df_db_objects_refresh.DfObjectRefresher(
            'Mock',
            lambda t: self.test_objs.keys(),
            self._db_read_objects,
            self._cache_update_object,
            self._cache_delete_id)

        refresher.read()
        refresher.update()
        refresher.delete()
        # Make sure the number of elements is correct
        self.assertEqual(len(self.test_objs),
                         self.TEST_ITEMS - self.ITEMS_TO_DELETE,
                         'Unexpected number of elements left in the cache')
        for item_id in self.deleted_objs:
            # Make sure we do not have the deleted items
            self.assertNotIn(item_id,
                             self.test_objs,
                             'Deleted object is still in the cache')

    def test_restart_df_controller(self):
        # Simulate restart df controller, in which case the local cache
        # will be empty and nothing will be deleted.
        fake_delete_method = mock.Mock()
        refresher = df_db_objects_refresh.DfObjectRefresher(
            'Mock',
            lambda t: set(),
            self._db_read_objects,
            self._cache_update_object,
            fake_delete_method)

        refresher.read()
        refresher.update()
        refresher.delete()

        self.assertFalse(fake_delete_method.called)
