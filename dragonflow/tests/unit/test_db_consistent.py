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

from mock import Mock

from dragonflow.db.api_nb import OvsPort
from dragonflow.db.db_consistent import DBConsistent
from dragonflow.tests import base as tests_base


class TestDBConsistent(tests_base.BaseTestCase):

    def setUp(self):

        super(TestDBConsistent, self).setUp()
        self.topology = Mock()
        self.nb_api = Mock()
        self.db_store = Mock()
        self.controller = Mock()

        self.topic = '111-222-333'

        self.lport_id1 = '1'
        self.ovs_port_id1 = '11'

        self.lport_id2 = '2'
        self.ovs_port_id2 = '22'

        self.lport_id3 = '3'
        self.ovs_port_id3 = '33'

        self.topology.ovs_to_lport_mapping = {
            self.ovs_port_id2: {
                'lport_id': self.lport_id2,
                'topic': self.topic
            },
            self.ovs_port_id3: {
                'lport_id': self.lport_id3,
                'topic': self.topic
            }
        }

        value1 = Mock()
        value1.get_id.return_value = self.ovs_port_id1
        value1.get_ofport.return_value = 1
        value1.get_name.return_value = ''
        value1.get_admin_state.return_value = 'True'
        value1.get_type.return_value = 'vm'
        value1.get_iface_id.return_value = self.lport_id1
        value1.get_peer.return_value = ''
        value1.get_attached_mac.return_value = ''
        value1.get_remote_ip.return_value = ''
        value1.get_tunnel_type.return_value = ''

        self.ovs_port1 = OvsPort(value1)

        self.topology.ovs_ports = {
            self.ovs_port_id1: self.ovs_port1
        }
        self.lport1 = Mock()
        self.lport1.get_topic.return_value = self.topic
        self.topology._get_lport.return_value = self.lport1

        self.db_consistent = DBConsistent(
                self.topology, self.nb_api, self.db_store, self.controller)

    def test_check_topology_info(self):
        self.db_consistent.check_topology_info()

        self.topology._add_to_topic_subscribed.assert_called_with(
            self.topic, self.lport_id1)
        self.topology._del_from_topic_subscribed.assert_any_call(
            self.topic, self.lport_id2)
        self.topology._del_from_topic_subscribed.assert_any_call(
            self.topic, self.lport_id3)

    def test_db_comparison(self):
        df_obj1 = FakeDfLocalObj(self.lport_id1, 1)
        df_obj2 = FakeDfLocalObj(self.lport_id2, 2)

        local_obj1 = FakeDfLocalObj(self.lport_id2, 1)
        local_obj2 = FakeDfLocalObj(self.lport_id3, 1)

        df_objs = [df_obj1, df_obj2]
        local_objs = [local_obj1, local_obj2]

        self.nb_api.get_all_logical_switches.return_value = df_objs
        self.db_store.get_lswitchs.return_value = local_objs

        self.nb_api.get_all_logical_ports.return_value = df_objs
        self.db_store.get_ports.return_value = local_objs

        self.nb_api.get_routers.return_value = df_objs
        self.db_store.get_routers.return_value = local_objs

        self.nb_api.get_security_groups.return_value = df_objs
        self.db_store.get_security_groups.return_value = local_objs

        self.nb_api.get_floatingips.return_value = df_objs
        self.db_store.get_floatingips.return_value = local_objs

        self.nb_api.get_publishers.return_value = df_objs
        self.db_store.get_publishers.return_value = local_objs

        self.db_consistent.handle_data_comparison(
                [self.topic], 'publisher', False)
        self.controller.publisher_updated.assert_called_with(df_obj1)
        self.controller.publisher_updated.assert_called_with(df_obj2)
        self.controller.publisher_deleted.assert_called_with(self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], 'lswitch', False)
        self.controller.logical_switch_updated.assert_called_with(df_obj1)
        self.controller.logical_switch_updated.assert_called_with(df_obj2)
        self.controller.logical_switch_deleted.assert_called_with(
                self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], 'port', False)
        self.controller.logical_port_created.assert_called_with(df_obj1)
        self.controller.logical_port_updated.assert_called_with(df_obj2)
        self.controller.logical_port_deleted.assert_called_with(
                self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], 'router', False)
        self.controller.router_updated.assert_called_with(df_obj1)
        self.controller.router_updated.assert_called_with(df_obj2)
        self.controller.router_deleted.assert_called_with(self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], 'router', False)
        self.controller.security_group_updated.assert_called_with(df_obj1)
        self.controller.security_group_updated.assert_called_with(df_obj2)
        self.controller.security_group_deleted.assert_called_with(
                self.lport_id3)

        self.db_consistent.handle_data_comparison(
                [self.topic], 'floatingip', False)
        self.controller.floatingip_updated.assert_called_with(df_obj1)
        self.controller.floatingip_updated.assert_called_with(df_obj2)
        self.controller.floatingip_deleted.assert_called_with(
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
