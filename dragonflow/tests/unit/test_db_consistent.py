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
from dragonflow.db import models
from dragonflow.tests import base as tests_base


class TestDBConsistent(tests_base.BaseTestCase):

    def setUp(self):
        super(TestDBConsistent, self).setUp()
        self.controller = mock.Mock()
        self.topology = self.controller.topology
        self.nb_api = self.controller.nb_api
        self.db_store = self.controller.db_store

        self.topic = '111-222-333'
        self.lport_id1 = '1'
        self.lport_id2 = '2'
        self.lport_id3 = '3'
        self.db_consistent = db_consistent.DBConsistencyManager(
                self.controller)

    def test_db_comparison(self):
        df_obj1 = FakeDfLocalObj(self.lport_id1, 1)
        df_obj2 = FakeDfLocalObj(self.lport_id2, 2)

        local_obj1 = FakeDfLocalObj(self.lport_id2, 1)
        local_obj2 = FakeDfLocalObj(self.lport_id3, 1)

        self.nb_api.get_all_logical_switches.return_value = [df_obj1, df_obj2]
        self.db_store.get_lswitchs.return_value = [local_obj1, local_obj2]

        self.nb_api.get_all_logical_ports.return_value = [df_obj1, df_obj2]
        self.db_store.get_ports.return_value = [local_obj1, local_obj2]

        self.nb_api.get_routers.return_value = [df_obj1, df_obj2]
        self.db_store.get_routers.return_value = [local_obj1, local_obj2]

        self.nb_api.get_security_groups.return_value = [df_obj1, df_obj2]
        self.db_store.get_security_groups.return_value = [
            local_obj1, local_obj2]

        self.nb_api.get_floatingips.return_value = [df_obj1, df_obj2]
        self.db_store.get_floatingips.return_value = [local_obj1, local_obj2]

        self.db_consistent.handle_data_comparison(
                [self.topic], models.LogicalSwitch.table_name, True)
        self.controller.update_lswitch.assert_any_call(df_obj1)
        self.controller.update_lswitch.assert_any_call(df_obj2)
        self.controller.delete_lswitch.assert_any_call(
                self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], models.LogicalPort.table_name, True)
        self.controller.update_lport.assert_any_call(df_obj1)
        self.controller.update_lport.assert_any_call(df_obj2)
        self.controller.delete_lport.assert_any_call(
                self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], models.LogicalRouter.table_name, True)
        self.controller.update_lrouter.assert_any_call(df_obj1)
        self.controller.update_lrouter.assert_any_call(df_obj2)
        self.controller.delete_lrouter.assert_any_call(self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], models.SecurityGroup.table_name, True)
        self.controller.update_secgroup.assert_any_call(df_obj1)
        self.controller.update_secgroup.assert_any_call(df_obj2)
        self.controller.delete_secgroup.assert_any_call(
                self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], models.Floatingip.table_name, True)
        self.controller.update_floatingip.assert_any_call(df_obj1)
        self.controller.update_floatingip.assert_any_call(df_obj2)
        self.controller.delete_floatingip.assert_any_call(
                self.lport_id3)


class FakeDfLocalObj(object):
    """To generate df_obj or local_obj for testing purposes only."""
    def __init__(self, id, version):
        self.id = id
        self.version = version

    def get_id(self):
        return self.id

    def get_version(self):
        return self.version
