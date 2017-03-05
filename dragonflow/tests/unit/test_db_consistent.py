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

from dragonflow.db import db_consistent
from dragonflow.tests import base as tests_base


class TestDBConsistent(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDBConsistent, self).setUp()
        self.controller = mock.MagicMock()

        self.topic = '111-222-333'
        self.obj_id0 = '0'
        self.obj_id1 = '1'
        self.obj_id2 = '2'
        self.obj_id3 = '3'
        self.obj_id4 = '4'
        self.db_consistent = db_consistent.DBConsistencyManager(
                self.controller)

    def _create_handler(self, local, nb):
        return db_consistent.VersionedModelHandler(
            model=mock.MagicMock(),
            db_store_func=mock.MagicMock(return_value=local),
            nb_api_func=mock.MagicMock(return_value=nb),
            update_handler=mock.MagicMock(),
            delete_handler=mock.MagicMock(),
        )

    def _create_versionneless_handler(self, local, nb):
        return db_consistent.ModelHandler(
            model=mock.MagicMock(),
            db_store_func=mock.MagicMock(return_value=local),
            nb_api_func=mock.MagicMock(return_value=nb),
            update_handler=mock.MagicMock(),
            delete_handler=mock.MagicMock(),
        )

    def test_direct_create(self):
        nb_obj = FakeDfLocalObj('1', 1)
        handler = self._create_handler([], [nb_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, True)
        handler._update_handler.assert_called_once_with(nb_obj)

    def test_indirect_create(self):
        nb_obj = FakeDfLocalObj('1', 1)
        handler = self._create_handler([], [nb_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_called_once_with(nb_obj)

    def test_indirect_create_versionless(self):
        nb_obj = FakeDfLocalObj('1', None)
        handler = self._create_versionneless_handler([], [nb_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_called_once_with(nb_obj)

    def test_indirect_create_older_version(self):
        new_obj = FakeDfLocalObj('1', 2)
        older_obj = FakeDfLocalObj('1', 1)
        handler = self._create_handler([], [new_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        handler._nb_api_func.return_value = [older_obj]
        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

    def test_indirect_create_aborted(self):
        nb_obj = FakeDfLocalObj('1', 2)
        handler = self._create_handler([], [nb_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        handler._db_store_func.return_value = [nb_obj]
        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

    def test_direct_delete(self):
        local_obj = FakeDfLocalObj('1', 1)
        handler = self._create_handler([local_obj], [])

        self.db_consistent.handle_data_comparison([self.topic], handler, True)
        handler._delete_handler.assert_called_once_with(local_obj)

    def test_indirect_delete(self):
        local_obj = FakeDfLocalObj('1', 1)
        handler = self._create_handler([local_obj], [])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._delete_handler.assert_not_called()

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._delete_handler.assert_called_once_with(local_obj)

    def test_indirect_delete_aborted(self):
        local_obj = FakeDfLocalObj('1', 1)
        handler = self._create_handler([local_obj], [])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._delete_handler.assert_not_called()

        handler._nb_api_func.return_value = [local_obj]
        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._delete_handler.assert_not_called()

    def test_direct_update(self):
        local_obj = FakeDfLocalObj('1', 1)
        nb_obj = FakeDfLocalObj('1', 2)
        handler = self._create_handler([local_obj], [nb_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, True)
        handler._update_handler.assert_called_once_with(nb_obj)

    def test_direct_update_same_version(self):
        obj = FakeDfLocalObj('1', 2)

        handler = self._create_handler([obj], [obj])
        self.db_consistent.handle_data_comparison([self.topic], handler, True)
        handler._update_handler.assert_not_called()

    def test_direct_update_versionless(self):
        local_obj = FakeDfLocalObj('1', None)
        nb_obj = FakeDfLocalObj('1', None)

        handler = self._create_versionneless_handler([local_obj], [nb_obj])
        self.db_consistent.handle_data_comparison([self.topic], handler, True)
        handler._update_handler.assert_called_once_with(nb_obj)

    def test_indirect_update(self):
        local_obj = FakeDfLocalObj('1', 1)
        nb_obj = FakeDfLocalObj('1', 2)
        handler = self._create_handler([local_obj], [nb_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_called_once_with(nb_obj)

    def test_indirect_update_versionless(self):
        local_obj = FakeDfLocalObj('1', None)
        nb_obj = FakeDfLocalObj('1', None)

        handler = self._create_versionneless_handler([local_obj], [nb_obj])
        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_called_once_with(nb_obj)

    def test_indirect_update_aborted(self):
        local_obj = FakeDfLocalObj('1', 1)
        nb_obj = FakeDfLocalObj('1', 2)
        handler = self._create_handler([local_obj], [nb_obj])

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        handler._db_store_func.return_value = [nb_obj]
        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

    def test_indirect_update_local_updated(self):
        old_obj = FakeDfLocalObj('1', 1)
        newer_obj = FakeDfLocalObj('1', 2)
        newest_obj = FakeDfLocalObj('1', 3)

        handler = self._create_handler([old_obj], [newest_obj])
        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        handler._db_store_func.return_value = [newer_obj]
        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_not_called()

        self.db_consistent.handle_data_comparison([self.topic], handler, False)
        handler._update_handler.assert_called_once_with(newest_obj)

    def test_direct_db_comparison(self):
        df_obj0 = FakeDfLocalObj(self.obj_id0, 0)
        df_obj1 = FakeDfLocalObj(self.obj_id1, 1)
        df_obj2 = FakeDfLocalObj(self.obj_id2, 2)
        df_obj3 = FakeDfLocalObj(self.obj_id4, 1)

        local_obj1 = FakeDfLocalObj(self.obj_id2, 1)
        local_obj2 = FakeDfLocalObj(self.obj_id3, 1)
        local_obj3 = FakeDfLocalObj(self.obj_id4, 0)

        handler = self._create_handler(
            [local_obj1, local_obj2, local_obj3],
            [df_obj0, df_obj1, df_obj2, df_obj3],
        )

        self.db_consistent.handle_data_comparison([self.topic], handler, True)
        handler._db_store_func.assert_called()
        handler._nb_api_func.assert_called()
        handler._update_handler.assert_any_call(df_obj0)
        handler._update_handler.assert_any_call(df_obj1)
        handler._update_handler.assert_any_call(df_obj2)
        handler._update_handler.assert_any_call(df_obj3)
        handler._delete_handler.assert_called_once_with(local_obj2)


class FakeDfLocalObj(object):
    """To generate df_obj or local_obj for testing purposes only."""
    def __init__(self, id, version):
        self.id = id
        self.version = version

    def is_newer_than(self, other):
        return self.version > other.version
