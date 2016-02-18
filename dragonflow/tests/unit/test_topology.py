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

from mock import Mock

from neutron.tests import base as tests_base

from dragonflow.controller.topology import Topology
from dragonflow.db.api_nb import OvsPort, LogicalPort, LogicalSwitch
from dragonflow.db.db_store import DbStore


class TestTopology(tests_base.BaseTestCase):

    topology = None
    db_store = None
    mock_nb_api = None
    mock_openflow_app = None
    mock_controller = None

    def setUp(self):

        super(TestTopology, self).setUp()
        self.db_store = DbStore()
        self.mock_nb_api = Mock(name="nb_api")
        self.mock_openflow_app = Mock(name="openflow_app")

        mock_controller = Mock(name="controller")
        mock_controller.get_db_store.return_value = self.db_store
        mock_controller.get_nb_api.return_value = self.mock_nb_api
        mock_controller.get_openflow_app.return_value = self.mock_openflow_app
        mock_controller.get_chassis_name.return_value = "test_chassis"

        self.mock_controller = mock_controller

        self.topology = Topology(self.mock_controller, True)

        # type is 1 means vm port
        self.ovs_port1_value = '''
            {
                "uuid": "ovs_port1",
                "ofport": 1,
                "name": "",
                "admin_state": "True",
                "type": 1,
                "iface_id": "lport1",
                "peer": "",
                "attached_mac": "",
                "remote_ip": "",
                "tunnel_type": ""
            }
            '''
        self.lport1_value = '''
            {
                "name": "lport1",
                "chassis": "test_chassis",
                "admin_state": "True",
                "ips": ["192.168.10.1"],
                "macs": ["112233445566"],
                "lswitch": "lswitch1",
                "tenant_id": "tenant1"
            }
            '''
        self.lswitch1_value = '''
            {
                "name": "lswitch1",
                "subnets": ["subnet1"]
            }
        '''

        self.ovs_port1 = OvsPort(self.ovs_port1_value)
        self.lport1 = LogicalPort(self.lport1_value)
        self.lswitch1 = LogicalSwitch(self.lswitch1_value)

    def test_vm_port_online(self):
        self.mock_nb_api.get_logical_port.return_value = self.lport1
        self.mock_nb_api.get_all_logical_switches.return_value = \
            [self.lswitch1]
        self.mock_nb_api.get_all_logical_ports.return_value = [self.lport1]
        self.mock_nb_api.get_routers.return_value = []
        self.mock_nb_api.get_security_groups.return_value = []
        self.mock_nb_api.get_floatingips.return_value = []

        self.topology.ovs_port_updated(self.ovs_port1)

        lport1_saved = self.db_store.get_local_port(self.lport1.get_id())
        self.mock_openflow_app.notify_local_vm_port_added.assert_called_with(
            lport1_saved)
        self.mock_nb_api.subscriber.register_topic.assert_called_with(
            self.lport1.get_tenant_id())

        lport1 = LogicalPort(self.lport1_value)
        lport1.set_external_value('ofport', self.ovs_port1.get_ofport())
        lport1.set_external_value('is_local', True)
        lport1.set_external_value('ovs_port_id', self.ovs_port1.get_id())
        assert lport1.__dict__ == lport1_saved.__dict__

    def test_vm_port_offline(self):
        self.mock_nb_api.get_logical_port.return_value = self.lport1
        self.mock_nb_api.get_all_logical_switches.return_value = \
            [self.lswitch1]
        self.mock_nb_api.get_all_logical_ports.return_value = [self.lport1]
        self.mock_nb_api.get_routers.return_value = []
        self.mock_nb_api.get_security_groups.return_value = []
        self.mock_nb_api.get_floatingips.return_value = []

        self.topology.ovs_port_updated(self.ovs_port1)

        self.topology.ovs_port_deleted(self.ovs_port1.get_id())

        self.mock_openflow_app.notify_local_vm_port_deleted.assert_called_with(
            self.lport1)
        self.mock_nb_api.subscriber.unregister_topic.assert_called_with(
            self.lport1.get_tenant_id())
