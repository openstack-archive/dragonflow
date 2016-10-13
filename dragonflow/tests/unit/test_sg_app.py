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

import netaddr

from dragonflow.db import api_nb
from dragonflow.tests.unit import test_app_base

COMMAND_ADD = 1
COMMAND_DELETE = 2


class TestSGApp(test_app_base.DFAppTestBase):
    apps_list = "sg_app.SGApp"

    def setUp(self):
        super(TestSGApp, self).setUp()
        self.app = self.open_flow_app.dispatcher.apps[0]
        self.mock_mod_flow = self.app.mod_flow
        self.security_group = test_app_base.fake_security_group
        self.fake_local_lport = test_app_base.fake_local_port1
        self.fake_remote_lport = test_app_base.fake_remote_port1

        self.datapath.ofproto.OFPFC_ADD = COMMAND_ADD
        self.datapath.ofproto.OFPFC_MODIFY = COMMAND_ADD
        self.datapath.ofproto.OFPFC_DELETE_STRICT = COMMAND_DELETE
        self.datapath.ofproto.OFPFC_DELETE = COMMAND_DELETE

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
            'id': 'fake_port2',
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

    def _get_call_count_of_del_flow(self):
        count_of_del_flow = 0
        call_args_list = self.mock_mod_flow.call_args_list
        if call_args_list:
            for call_arg in call_args_list:
                command = call_arg[1].get('command')
                if command == COMMAND_DELETE:
                    count_of_del_flow += 1
        return count_of_del_flow

    def _get_call_count_of_add_flow(self):
        call_counts = self.mock_mod_flow.call_count
        count_of_del_flow = self._get_call_count_of_del_flow()
        return call_counts - count_of_del_flow

    def test_add_delete_lport(self):
        # create fake security group
        self.controller.security_group_updated(self.security_group)
        self.mock_mod_flow.assert_not_called()

        # add remote port before adding any local port
        self.controller.logical_port_created(self.fake_remote_lport)
        self.mock_mod_flow.assert_not_called()

        # remove remote port before adding any local port
        self.controller.logical_port_deleted('fake_remote_port')
        self.mock_mod_flow.assert_not_called()

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
        self.assertEqual(8, self._get_call_count_of_add_flow())
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
        self.assertEqual(5, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # remove local port two
        self.controller.logical_port_deleted('fake_port2')
        # remove flows:
        # 1. a flow in ingress conntrack table
        # 2. a associating flow in ingress secgroup table
        # 3. a flow in egress conntrack table
        # 4. a associating flow in egress secgroup table
        # 5. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        self.assertEqual(5, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()

        # add remote port after adding a local port
        self.controller.logical_port_created(self.fake_remote_lport)
        # add flows:
        # 1. a ingress rule flow (caused by IP addresses represent
        # remote_group_id changed) in ingress secgroup table
        self.assertEqual(1, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # remove remote port after adding a local port
        self.controller.logical_port_deleted('fake_remote_port')
        # remove flows:
        # 1. a ingress rule flow (caused by IP addresses represent
        # remote_group_id changed) in ingress secgroup table
        self.assertEqual(1, self._get_call_count_of_del_flow())
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
        self.assertEqual(9, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id1')
        self.mock_mod_flow.assert_not_called()

    def test_update_lport(self):
        # create fake security group
        self.controller.security_group_updated(self.security_group)

        # add local port
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport_version = fake_local_lport.lport['version']
        self.controller.logical_port_created(fake_local_lport)
        self.mock_mod_flow.reset_mock()

        # create another fake security group
        fake_security_group2 = self._get_another_security_group()
        self.controller.security_group_updated(fake_security_group2)

        # update the association of the lport to a new security group
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.lport['security_groups'] = \
            ['fake_security_group_id2']
        fake_local_lport_version += 1
        fake_local_lport.lport['version'] = fake_local_lport_version
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
        self.assertEqual(6, self._get_call_count_of_add_flow())
        self.assertEqual(7, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()

        # update the association of the lport to no security group
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.lport['security_groups'] = []
        fake_local_lport_version += 1
        fake_local_lport.lport['version'] = fake_local_lport_version
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
        self.assertEqual(9, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()

        # remove local port
        self.controller.logical_port_deleted('fake_port2')

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id1')
        self.controller.security_group_deleted('fake_security_group_id2')

    def test_add_del_security_group_rule(self):
        # create another fake security group
        security_group = self._get_another_security_group()
        security_group_version = security_group.secgroup['version']
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
        security_group_version += 1
        security_group.secgroup['version'] = security_group_version
        self.controller.security_group_updated(security_group)
        # add flows:
        # 1. a egress rule flow in egress secgroup table
        self.assertEqual(1, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # remove a security group rule
        security_group = self._get_another_security_group()
        security_group_version += 1
        security_group.secgroup['version'] = security_group_version
        self.controller.security_group_updated(security_group)
        # remove flows:
        # 1. a egress rule flow in egress secgroup table
        self.assertEqual(1, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()

        # remove local ports
        self.controller.logical_port_deleted('fake_port2')
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.security_group_deleted('fake_security_group_id2')

    def test_aggregating_flows_for_addresses(self):
        # add one address
        old_cidr_set = netaddr.IPSet(['192.168.10.6'])
        new_cidr_set, added_cidr, deleted_cidr = \
            self.app._get_cidr_changes_after_adding_one_address(
                old_cidr_set, '192.168.10.7')
        expected_new_cidr_set = netaddr.IPSet(['192.168.10.6/31'])
        added_cidr = '192.168.10.6/31'
        deleted_cidr = '192.168.10.6/32'
        self.assertEquals(new_cidr_set, expected_new_cidr_set)
        self.assertEquals(added_cidr, added_cidr)
        self.assertEquals(deleted_cidr, deleted_cidr)

        # remove one address
        old_cidr_set = new_cidr_set
        new_cidr_set, added_cidr, deleted_cidr = \
            self.app._get_cidr_changes_after_removing_one_address(
                old_cidr_set, '192.168.10.7')
        expected_new_cidr_set = netaddr.IPSet(['192.168.10.6/32'])
        added_cidr = '192.168.10.6/32'
        deleted_cidr = '192.168.10.6/31'
        self.assertEquals(new_cidr_set, expected_new_cidr_set)
        self.assertEquals(added_cidr, added_cidr)
        self.assertEquals(deleted_cidr, deleted_cidr)

    def test_aggregating_flows_for_port_range(self):
        # compute port match list
        port_range_min = 20
        port_range_max = 30
        port_match_list = self.app._get_port_match_list_from_port_range(
                port_range_min, port_range_max)
        expected_port_match_list = [(20, 0xfffc), (24, 0xfffc), (28, 0xfffe),
                                    (30, 0xffff)]

        self.assertItemsEqual(port_match_list, expected_port_match_list)
