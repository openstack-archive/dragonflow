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

from dragonflow.db import api_nb
from dragonflow.tests.unit import test_app_base


class TestSGApp(test_app_base.DFAppTestBase):
    apps_list = "sg_app.SGApp"

    def setUp(self):
        super(TestSGApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]
        self.mock_mod_flow = mock.Mock(name='mod_flow')
        self.app.mod_flow = self.mock_mod_flow
        self.security_group = test_app_base.fake_security_group
        self.fake_local_lport = test_app_base.fake_local_port1
        self.fake_remote_lport = test_app_base.fake_remote_port1

    def _get_another_local_lport(self):
        fake_local_port = api_nb.LogicalPort("{}")
        fake_local_port.lport = {
            'subnets': ['fake_subnet1'],
            'binding_profile': {},
            'macs': ['fa:16:3e:8c:2e:12'],
            'name': '',
            'allowed_address_pairs': [],
            'lswitch': 'fake_switch1',
            'enabled': True,
            'topic': 'fake_tenant1',
            'ips': ['10.0.0.10'],
            'device_owner': 'compute:None',
            'chassis': 'fake_host',
            'version': 2,
            'tunnel_key': 5,
            'port_security_enabled': True,
            'binding_vnic_type': 'normal',
            'id': 'fake_port3',
            'security_groups': ['fake_security_group_id1'],
            'device_id': 'fake_device_id'}
        fake_local_port.external_dict = {'is_local': True,
                                         'segmentation_id': 23,
                                         'ofport': 20,
                                         'network_type': 'vxlan',
                                         'local_network_id': 1}
        return fake_local_port

    def _get_another_security_group(self):
        fake_security_group = api_nb.SecurityGroup("{}")
        fake_security_group.secgroup = {
            "description": "",
            "name": "fake_security_group",
            "topic": "fake_tenant1",
            "version": 5,
            "id": "fake_security_group_id2",
            "rules": [{"direction": "egress",
                       "security_group_id": "fake_security_group_id2",
                       "ethertype": "IPv4",
                       "topic": "fake_tenant1",
                       "protocol": "tcp",
                       "port_range_max": None,
                       "port_range_min": None,
                       "remote_group_id": None,
                       "remote_ip_prefix": "192.168.0.0/16",
                       "id": "fake_security_group_rule_3"},
                      {"direction": "ingress",
                       "security_group_id": "fake_security_group_id2",
                       "ethertype": "IPv4",
                       "topic": "fake_tenant1",
                       "port_range_max": None,
                       "port_range_min": None,
                       "protocol": None,
                       "remote_group_id": "fake_security_group_id2",
                       "remote_ip_prefix": None,
                       "id": "fake_security_group_rule_4"}]}
        return fake_security_group

    def test_add_delete_lport(self):
        # create fake security group
        self.controller.security_group_updated(self.security_group)
        self.mock_mod_flow.assert_not_called()
        self.mock_mod_flow.reset_mock()

        # add remote port before adding any local port
        self.controller.logical_port_created(self.fake_remote_lport)
        self.mock_mod_flow.assert_not_called()
        self.mock_mod_flow.reset_mock()

        # add remote port before adding any local port
        self.controller.logical_port_deleted('fake_port2')
        self.mock_mod_flow.assert_not_called()
        self.mock_mod_flow.reset_mock()

        # add local port one
        self.controller.logical_port_created(self.fake_local_lport)
        # add flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow in ingress secgroup table
        # 6. the permit flow in ingress secgroup table
        # 7. a egress rule flow in egress secgroup table
        # 8. the permit flow in egress secgroup table
        self.assertEqual(8, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # add local port two
        fake_local_lport2 = self._get_another_local_lport()
        self.controller.logical_port_created(fake_local_lport2)
        # add flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        self.assertEqual(5, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove local port two
        self.controller.logical_port_deleted('fake_port3')
        # remove flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        self.assertEqual(5, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # add remote port after adding a local port
        self.controller.logical_port_created(self.fake_remote_lport)
        # add flows:
        # 1. a ingress rule flow (caused by IP addresses represent
        # remote_group_id changed) in ingress secgroup table
        self.assertEqual(1, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove remote port after adding a local port
        self.controller.logical_port_deleted('fake_port2')
        # remove flows:
        # 1. a ingress rule flow (caused by IP addresses represent
        # remote_group_id changed) in ingress secgroup table
        self.assertEqual(1, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove local port one
        self.controller.logical_port_deleted('fake_port1')
        # remove flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        # 6. ingress rules deleted by cookie in ingress secgroup table
        # 7. egress rules deleted by cookie in egress secgroup table
        # 8. the permit flow in ingress secgroup table
        # 9. the permit flow in egress secgroup table
        self.assertEqual(9, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id1')
        self.mock_mod_flow.assert_not_called()
        self.mock_mod_flow.reset_mock()

    def test_update_lport(self):
        # create fake security group
        self.controller.security_group_updated(self.security_group)

        # add local port
        fake_local_lport = self._get_another_local_lport()
        self.controller.logical_port_created(fake_local_lport)
        self.mock_mod_flow.reset_mock()

        # create another fake security group
        fake_security_group2 = self._get_another_security_group()
        self.controller.security_group_updated(fake_security_group2)

        # update the association of the lport to a new security group
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.lport['security_groups'] = \
            ['fake_security_group_id2']
        self.controller.logical_port_updated(fake_local_lport)
        # add flows:
        # 1. a associating flow in ingress secgroup table
        # 2. a associating flow in egress secgroup table
        # 3. a ingress rule flow in ingress secgroup table
        # 4. the permit flow in ingress secgroup table
        # 5. a egress rule flow in egress secgroup table
        # 6. the permit flow in egress secgroup table
        # remove flows:
        # 1. a associating flow in ingress secgroup table
        # 2. a associating flow in egress secgroup table
        # 3. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        # 4. ingress rules deleted by cookie in ingress secgroup table
        # 5. egress rules deleted by cookie in egress secgroup table
        # 6. the permit flow in ingress secgroup table
        # 7. the permit flow in egress secgroup table
        self.assertEqual(13, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # update the association of the lport to no security group
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.lport['security_groups'] = []
        self.controller.logical_port_updated(fake_local_lport)
        # remove flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        # 6. ingress rules deleted by cookie in ingress secgroup table
        # 7. egress rules deleted by cookie in egress secgroup table
        # 8. the permit flow in ingress secgroup table
        # 9. the permit flow in egress secgroup table
        self.assertEqual(9, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove local port
        self.controller.logical_port_deleted('fake_port3')

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id1')
        self.controller.security_group_deleted('fake_security_group_id2')

    def test_add_del_security_group_rule(self):
        # create another fake security group
        security_group = self._get_another_security_group()
        self.controller.security_group_updated(security_group)

        # add local port
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.lport['security_groups'] = \
            ['fake_security_group_id2']
        self.controller.logical_port_created(fake_local_lport)
        self.mock_mod_flow.reset_mock()

        # add a security group rule
        security_group = self._get_another_security_group()
        security_group.secgroup['rules'].append({
            "direction": "egress",
            "security_group_id": "fake_security_group_id2",
            "ethertype": "IPv4",
            "topic": "fake_tenant1",
            "protocol": 'udp',
            "port_range_max": None,
            "port_range_min": None,
            "remote_group_id": None,
            "remote_ip_prefix": None,
            "id": "fake_security_group_rule_5"})
        self.controller.security_group_updated(security_group)
        # add flows:
        # 1. a egress rule flow in egress secgroup table
        self.assertEqual(1, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove a security group rule
        security_group = self._get_another_security_group()
        self.controller.security_group_updated(security_group)
        # remove flows:
        # 1. a egress rule flow in egress secgroup table
        self.assertEqual(1, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove local ports
        self.controller.logical_port_deleted('fake_port3')
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id2')

    def test_aggregating_flows_for_addresses(self):
        # create fake security group
        self.controller.security_group_updated(self.security_group)

        # add local port one
        self.controller.logical_port_created(self.fake_local_lport)
        self.mock_mod_flow.reset_mock()

        # add local port two
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.lport['ips'] = \
            ['10.0.0.7']
        self.controller.logical_port_created(fake_local_lport)
        # add flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow(nw_src=10.0.0.6/31) in ingress secgroup table
        # remove flows:
        # 1. a ingress rule flow(nw_src=10.0.0.6/32) in ingress secgroup table
        self.assertEqual(6, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove local ports
        self.controller.logical_port_deleted('fake_port1')
        self.controller.logical_port_deleted('fake_port3')
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id1')

    def test_aggregating_flows_for_port_range(self):
        # create another fake security group
        security_group = self._get_another_security_group()
        security_group.secgroup['rules'] = [
            {"direction": "egress",
             "security_group_id": "fake_security_group_id2",
             "ethertype": "IPv4",
             "topic": "fake_tenant1",
             "port_range_max": 83,
             "port_range_min": 80,
             "protocol": 6,
             "remote_group_id": None,
             "remote_ip_prefix": None,
             "id": "fake_security_group_rule_5"},
            {"direction": "ingress",
             "security_group_id": "fake_security_group_id2",
             "ethertype": "IPv4",
             "topic": "fake_tenant1",
             "port_range_max": 53,
             "port_range_min": 52,
             "protocol": 17,
             "remote_group_id": "fake_security_group_id2",
             "remote_ip_prefix": None,
             "id": "fake_security_group_rule_6"}]
        self.controller.security_group_updated(security_group)

        # add local port
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.lport['security_groups'] = \
            ['fake_security_group_id2']
        self.controller.logical_port_created(fake_local_lport)
        # add flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow in ingress secgroup table
        # 6. the permit flow in ingress secgroup table
        # 7. a egress rule flow in egress secgroup table
        # 8. the permit flow in egress secgroup table
        self.assertEqual(8, self.mock_mod_flow.call_count)
        self.mock_mod_flow.reset_mock()

        # remove local ports
        self.controller.logical_port_deleted('fake_port3')
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id2')
