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
        self.lport_id0 = '0'
        self.lport_id1 = '1'
        self.lport_id2 = '2'
        self.lport_id3 = '3'
        self.lport_id4 = '4'
        self.db_consistent = db_consistent.DBConsistencyManager(
                self.controller)

    def test_db_comparison(self):
        df_obj0 = FakeDfLocalObj(self.lport_id0, 0)
        df_obj1 = FakeDfLocalObj(self.lport_id1, 1)
        df_obj2 = FakeDfLocalObj(self.lport_id2, 2)
        df_obj3 = FakeDfLocalObj(self.lport_id4, 1)

        local_obj1 = FakeDfLocalObj(self.lport_id2, 1)
        local_obj2 = FakeDfLocalObj(self.lport_id3, 1)
        local_obj3 = FakeDfLocalObj(self.lport_id4, 0)

        handler = db_consistent.ModelHandler(
            model=mock.MagicMock(),
            db_store_func=mock.MagicMock(
                return_value=[
                    local_obj1,
                    local_obj2,
                    local_obj3,
                ]
            ),
            nb_api_func=mock.MagicMock(
                return_value=[
                    df_obj0,
                    df_obj1,
                    df_obj2,
                    df_obj3,
                ],
            ),
            update_handler=mock.MagicMock(),
            delete_handler=mock.MagicMock(),
        )

        self.db_consistent.handle_data_comparison([self.topic], handler, True)
        handler._db_store_func.assert_called()
        handler._nb_api_func.assert_called()
        handler._update_handler.assert_any_call(df_obj0)
        handler._update_handler.assert_any_call(df_obj1)
        handler._update_handler.assert_any_call(df_obj2)
        handler._update_handler.assert_any_call(df_obj3)
        handler._delete_handler.assert_any_call(
            handler._model,
            self.lport_id3,
        )


class FakeDfLocalObj(object):
    """To generate df_obj or local_obj for testing purposes only."""
    def __init__(self, id, version):
        self.id = id
        self.version = version
