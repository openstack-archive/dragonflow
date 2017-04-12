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
import netaddr
import random
import string

from neutron.agent.common import utils
from neutron_lib import constants as n_const

from dragonflow.controller.common import cidr_list
from dragonflow.db import models as db_models
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
        self.mock_execute = utils.execute

        self.datapath.ofproto.OFPFC_ADD = COMMAND_ADD
        self.datapath.ofproto.OFPFC_MODIFY = COMMAND_ADD
        self.datapath.ofproto.OFPFC_DELETE_STRICT = COMMAND_DELETE
        self.datapath.ofproto.OFPFC_DELETE = COMMAND_DELETE

    def _get_ip_prefix(self, is_ipv6):
        if is_ipv6:
            return "1111::/64"
        return "192.168.0.0/16"

    def _get_ether_type(self, is_ipv6):
        if is_ipv6:
            return n_const.IPv6
        return n_const.IPv4

    def _get_another_local_lport(self):
        fake_local_port = db_models.LogicalPort("{}")
        fake_local_port.inner_obj = {
            'subnets': ['fake_subnet1'],
            'binding_profile': {},
            'macs': ['fa:16:3e:8c:2e:12'],
            'name': '',
            'allowed_address_pairs': [],
            'lswitch': 'fake_switch1',
            'enabled': True,
            'topic': 'fake_tenant1',
            'ips': ['10.0.0.10', '2222:2222::2'],
            'device_owner': 'compute:None',
            'chassis': 'fake_host',
            'version': 2,
            'unique_key': 5,
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

    def _get_another_security_group(self, is_ipv6=False):
        fake_security_group = db_models.SecurityGroup("{}")
        fake_security_group.inner_obj = {
            "description": "",
            "name": "fake_security_group",
            "topic": "fake_tenant1",
            "version": 5,
            "unique_key": 2,
            "id": "fake_security_group_id2",
            "rules": [{"direction": "egress",
                       "security_group_id": "fake_security_group_id2",
                       "ethertype": self._get_ether_type(is_ipv6),
                       "topic": "fake_tenant1",
                       "protocol": "tcp",
                       "port_range_max": None,
                       "port_range_min": None,
                       "remote_group_id": None,
                       "remote_ip_prefix": self._get_ip_prefix(is_ipv6),
                       "id": "fake_security_group_rule_5"},
                      {"direction": "ingress",
                       "security_group_id": "fake_security_group_id2",
                       "ethertype": self._get_ether_type(is_ipv6),
                       "topic": "fake_tenant1",
                       "port_range_max": None,
                       "port_range_min": None,
                       "protocol": None,
                       "remote_group_id": "fake_security_group_id2",
                       "remote_ip_prefix": None,
                       "id": "fake_security_group_rule_6"}]}
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

    def _get_expected_conntrack_cmd(self, ethertype, protocol, nw_src, nw_dst,
                                    zone):
        cmd = ['conntrack', '-D']
        if protocol:
            cmd.extend(['-p', str(protocol)])
        cmd.extend(['-f', ethertype.lower()])
        if nw_src:
            cmd.extend(['-s', nw_src])
        if nw_dst:
            cmd.extend(['-d', nw_dst])
        if zone:
            cmd.extend(['-w', str(zone)])

        return mock.call(cmd, run_as_root=True, check_exit_code=True,
                         extra_ok_codes=[1])

    def test_add_delete_lport(self):
        # create fake security group
        self.controller.update_secgroup(self.security_group)
        self.mock_mod_flow.assert_not_called()

        # add remote port before adding any local port
        self.controller.update_lport(self.fake_remote_lport)
        self.mock_mod_flow.assert_not_called()

        # remove remote port before adding any local port
        self.controller.delete_lport(self.fake_remote_lport.get_id())
        self.mock_mod_flow.assert_not_called()

        # add local port one
        self.controller.update_lport(self.fake_local_lport)
        # add flows:
        # 1. a flow in ingress conntrack table (ipv4)
        # 2. a flow in ingress conntrack table (ipv6)
        # 3. a associating flow (conjunction) in ingress secgroup table (ipv4)
        # 4. a associating flow (conjunction) in ingress secgroup table (ipv6)
        # 5. a flow in egress conntrack table (ipv4)
        # 6. a flow in egress conntrack table (ipv6)
        # 7. a associating flow (conjunction) in egress secgroup table (ipv4)
        # 8. a associating flow (conjunction) in egress secgroup table (ipv6)
        # 9. a ingress rule flow (ipv4) in ingress secgroup table
        # 10. a ingress rule flow (ipv6) in ingress secgroup table
        # 11. the permit flow in ingress secgroup table
        # 12. a egress rule flow (ipv4) in egress secgroup table
        # 13. a egress rule flow (ipv6) in egress secgroup table
        # 14. the permit flow in egress secgroup table

        self.assertEqual(14, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # add local port two
        fake_local_lport2 = self._get_another_local_lport()

        self.controller.update_lport(fake_local_lport2)
        # add flows:
        # 1. a flow in ingress conntrack table (ipv4)
        # 2. a flow in ingress conntrack table (ipv6)
        # 3. a associating flow in ingress secgroup table
        # 4. a flow in egress conntrack table (ipv4)
        # 5. a flow in egress conntrack table (ipv6)
        # 6. a associating flow in egress secgroup table
        # 7-8. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table

        self.assertEqual(8, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # remove local port two
        self.controller.delete_lport(fake_local_lport2.get_id())
        # remove flows:
        # 1. a flow in ingress conntrack table (ipv4)
        # 2. a flow in ingress conntrack table (ipv6)
        # 3. a associating flow in ingress secgroup table
        # 4. a flow in egress conntrack table (ipv4)
        # 5. a flow in egress conntrack table (ipv6)
        # 6. a associating flow in egress secgroup table (ipv4)
        # 7. a associating flow in egress secgroup table (ipv6)
        # 8. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table (ipv4 only)
        self.assertEqual(8, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()
        expected_conntrack_cmd1 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol='udp', nw_src='10.0.0.10',
            nw_dst=None, zone=1)
        expected_conntrack_cmd2 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol=None, nw_src=None,
            nw_dst='10.0.0.10', zone=1)
        expected_conntrack_cmd3 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol=None, nw_src='10.0.0.10',
            nw_dst='10.0.0.6', zone=1)

        expected_conntrack_cmd4 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv6, protocol='udp', nw_src='2222:2222::2',
            nw_dst=None, zone=1)

        expected_conntrack_cmd5 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv6, protocol=None, nw_src=None,
            nw_dst='2222:2222::2', zone=1)
        expected_conntrack_cmd6 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv6, protocol=None, nw_src='2222:2222::2',
            nw_dst='2222:2222::3', zone=1)
        self.mock_execute.assert_has_calls([expected_conntrack_cmd1,
                                            expected_conntrack_cmd2,
                                            expected_conntrack_cmd3,
                                            expected_conntrack_cmd4,
                                            expected_conntrack_cmd5,
                                            expected_conntrack_cmd6],
                                           any_order=True)
        self.mock_execute.reset_mock()

        # add remote port after adding a local port
        self.controller.update_lport(self.fake_remote_lport)
        # add flows:
        # 1. a ingress rule flow (caused by IP addresses represent
        # remote_group_id changed) in ingress secgroup table
        self.assertEqual(1, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # remove remote port after adding a local port
        self.controller.delete_lport(self.fake_remote_lport.get_id())
        # remove flows:
        # 1. a ingress rule flow (caused by IP addresses represent
        # remote_group_id changed) in ingress secgroup table
        self.assertEqual(1, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()
        expected_conntrack_cmd1 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol=None, nw_src='10.0.0.8',
            nw_dst='10.0.0.6', zone=1)
        self.mock_execute.assert_has_calls([expected_conntrack_cmd1],
                                           any_order=True)
        self.mock_execute.reset_mock()

        # remove local port one
        self.controller.delete_lport(self.fake_local_lport.get_id())
        # remove flows:
        # 1. a flow in ingress conntrack table (ipv4)
        # 2. a flow in ingress conntrack table(ipv6)
        # 3. a associating flow (conjunction) in ingress secgroup table (ipv4)
        # 4. a associating flow (conjunction) in ingress secgroup table (ipv6)
        # 5. a flow in egress conntrack table (ipv4)
        # 6. a flow in egress conntrack table (ipv6)
        # 7. a associating flow in egress secgroup table (ipv4)
        # 8. a associating flow in egress secgroup table (ipv6)
        # 9. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        # 10-11. ingress rules deleted by cookie in ingress secgroup table
        #    (ipv4, ipv6)
        # 12-13. egress rules deleted by cookie in egress secgroup table (ipv4,
        #    ipv6)
        # 14. the permit flow (ipv4) in ingress secgroup table
        # 15. the permit flow (ipv6) in ingress secgroup table
        # 16. the permit flow in egress secgroup table
        self.assertEqual(16, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()
        expected_conntrack_cmd1 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol='udp', nw_src='10.0.0.6',
            nw_dst=None, zone=1)
        expected_conntrack_cmd2 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol=None, nw_src=None,
            nw_dst='10.0.0.6', zone=1)
        expected_conntrack_cmd3 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv6, protocol='udp', nw_src='2222:2222::3',
            nw_dst=None, zone=1)
        expected_conntrack_cmd4 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv6, protocol=None, nw_src=None,
            nw_dst='2222:2222::3', zone=1)
        self.mock_execute.assert_has_calls([expected_conntrack_cmd1,
                                            expected_conntrack_cmd2,
                                            expected_conntrack_cmd3,
                                            expected_conntrack_cmd4],
                                           any_order=True)
        self.mock_execute.reset_mock()

        # delete fake security group
        self.controller.delete_secgroup(self.security_group.get_id())
        self.mock_mod_flow.assert_not_called()

    def test_update_lport(self):
        # create fake security group
        self.controller.update_secgroup(self.security_group)

        # add local port
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport_version = fake_local_lport.inner_obj['version']
        self.controller.update_lport(fake_local_lport)
        self.mock_mod_flow.reset_mock()

        # create another fake security group
        fake_security_group2 = self._get_another_security_group(True)
        self.controller.update_secgroup(fake_security_group2)

        # update the association of the lport to a new security group
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.inner_obj['security_groups'] = \
            ['fake_security_group_id2']
        fake_local_lport_version += 1
        fake_local_lport.inner_obj['version'] = fake_local_lport_version
        self.controller.update_lport(fake_local_lport)
        # add flows:
        # 1. a associating flow (conjunction) in ingress secgroup table (ipv4)
        # 2. a associating flow (conjunction) in ingress secgroup table (ipv6)
        # 3. a associating flow in egress secgroup table (ipv4)
        # 4. a associating flow in egress secgroup table (ipv6)
        # 5. a ingress rule flow in ingress secgroup table
        # 6. the permit flow in ingress secgroup table (new ipv6 rule)
        # 7. a egress rule flow in egress secgroup table
        # 8. the permit flow in egress secgroup table (new ipv6 rule)
        # remove flows:
        # 1-2. a associating flow in ingress secgroup table (ipv4, ipv6)
        # 3-4. a associating flow in egress secgroup table (ipv4, ipv6)
        # 5-6. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table (ipv4, ipv6)
        # 7-8. ingress rules deleted by cookie in ingress secgroup table
        # 9-10. egress rules deleted by cookie in egress secgroup table
        # 11. the permit flow in ingress secgroup table
        # 12. the permit flow in egress secgroup table
        self.assertEqual(8, self._get_call_count_of_add_flow())
        self.assertEqual(12, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()
        expected_conntrack_cmd1 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol='udp', nw_src='10.0.0.10',
            nw_dst=None, zone=1)
        expected_conntrack_cmd2 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol=None, nw_src=None,
            nw_dst='10.0.0.10', zone=1)
        self.mock_execute.assert_has_calls([expected_conntrack_cmd1,
                                            expected_conntrack_cmd2],
                                           any_order=True)
        self.mock_execute.reset_mock()

        # update the association of the lport to no security group
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.inner_obj['security_groups'] = []
        fake_local_lport_version += 1
        fake_local_lport.inner_obj['version'] = fake_local_lport_version
        self.controller.update_lport(fake_local_lport)
        # remove flows:
        # 1-2. a flow in ingress conntrack table (ipv4, ipv6)
        # 3-4. a associating flow in ingress secgroup table (ipv4, ipv6)
        # 5-6. a flow in egress conntrack table (ipv4, ipv6)
        # 7-8. a associating flow in egress secgroup table (ipv4, ipv6)
        # 9. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table
        # 10. ingress rule deleted by cookie in ingress secgroup table
        # 11. egress rule deleted by cookie in egress secgroup table
        # 12. the permit flow in ingress secgroup table
        # 13. the permit flow in egress secgroup table
        self.assertEqual(13, self._get_call_count_of_del_flow())

        self.mock_mod_flow.reset_mock()
        # Only IPv6 rules were deleted
        expected_conntrack_cmd1 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv6, protocol='tcp', nw_src='2222:2222::2',
            nw_dst=None, zone=1)
        expected_conntrack_cmd2 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv6, protocol=None, nw_src=None,
            nw_dst='2222:2222::2', zone=1)

        self.mock_execute.assert_has_calls([expected_conntrack_cmd1,
                                            expected_conntrack_cmd2],
                                           any_order=True)
        self.mock_execute.reset_mock()

        # remove local port
        self.controller.delete_lport(fake_local_lport.get_id())

        # delete fake security group
        self.controller.delete_secgroup(self.security_group.get_id())
        self.controller.delete_secgroup(fake_security_group2.get_id())

    def test_add_del_security_group_rule(self):
        # create another fake security group
        security_group = self._get_another_security_group()
        security_group_version = security_group.inner_obj['version']
        self.controller.update_secgroup(security_group)

        # add local port
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.inner_obj['security_groups'] = \
            ['fake_security_group_id2']
        self.controller.update_lport(fake_local_lport)
        self.mock_mod_flow.reset_mock()
        self.mock_execute.reset_mock()

        # add a security group rule
        security_group = self._get_another_security_group()
        security_group.inner_obj['rules'].append({
            "direction": "egress",
            "security_group_id": "fake_security_group_id2",
            "ethertype": n_const.IPv4,
            "topic": "fake_tenant1",
            "protocol": 'udp',
            "port_range_max": None,
            "port_range_min": None,
            "remote_group_id": None,
            "remote_ip_prefix": None,
            "id": "fake_security_group_rule_5"})
        security_group_version += 1
        security_group.inner_obj['version'] = security_group_version
        self.controller.update_secgroup(security_group)
        # add flows:
        # 1. a egress rule flow in egress secgroup table
        self.assertEqual(1, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # remove a security group rule
        security_group = self._get_another_security_group()
        security_group_version += 1
        security_group.inner_obj['version'] = security_group_version
        self.controller.update_secgroup(security_group)
        # remove flows:
        # 1. a egress rule flow in egress secgroup table
        self.assertEqual(1, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()
        expected_conntrack_cmd1 = self._get_expected_conntrack_cmd(
            ethertype=n_const.IPv4, protocol='udp', nw_src='10.0.0.10',
            nw_dst=None, zone=1)
        self.mock_execute.assert_has_calls([expected_conntrack_cmd1],
                                           any_order=True)
        self.mock_execute.reset_mock()

        # remove local ports
        self.controller.delete_lport(fake_local_lport.get_id())
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.delete_secgroup(security_group.get_id())

    def test_support_allowed_address_pairs(self):
        # create fake security group
        self.controller.update_secgroup(self.security_group)

        # add a local port with allowed address pairs
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.inner_obj["allowed_address_pairs"] = [
            {'ip_address': '10.0.0.100',
             'mac_address': 'fa:16:3e:8c:2e:12'}
        ]
        fake_local_lport_version = fake_local_lport.inner_obj['version']
        self.controller.update_lport(fake_local_lport)
        # add flows:
        # 1-2. a flow in ingress conntrack table (ipv4, ipv6)
        # 3-4. a associating flow in ingress secgroup table (ipv4, ipv6)
        # 5-6. a flow in egress conntrack table (ipv4, ipv6)
        # 7-8. a associating flow in egress secgroup table (ipv4, ipv6)
        # 9-10. a ingress rule flow in ingress secgroup table(using fixed ip:
        #      ipv4, ipv6)
        # 11. a ingress rule flow in ingress secgroup table(using ip in allowed
        #    address pairs)
        # 12. the permit flow in ingress secgroup table
        # 13-14. a egress rule flow in egress secgroup table (ipv4, ipv6)
        # 15. the permit flow in egress secgroup table
        self.assertEqual(15, self._get_call_count_of_add_flow())
        self.mock_mod_flow.reset_mock()

        # update allowed address pairs of the lport
        fake_local_lport = self._get_another_local_lport()
        fake_local_lport.inner_obj["allowed_address_pairs"] = [
            {'ip_address': '10.0.0.200',
             'mac_address': 'fa:16:3e:8c:2e:12'}
        ]
        fake_local_lport_version += 1
        fake_local_lport.inner_obj['version'] = fake_local_lport_version
        self.controller.update_lport(fake_local_lport)
        # add flows:
        # 1. a ingress rule flow in ingress secgroup table(using ip in the new
        #    allowed address pairs)
        # remove flows:
        # 1. a ingress rule flow in ingress secgroup table(using ip in the old
        #    allowed address pairs)
        self.assertEqual(1, self._get_call_count_of_add_flow())
        self.assertEqual(1, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()

        # remove local port
        self.controller.delete_lport(fake_local_lport.get_id())
        # remove flows:
        # 1-2. a flow in ingress conntrack table (ipv4, ipv6)
        # 3-4. a associating flow in ingress secgroup table (ipv4, ipv6)
        # 5-6. a flow in egress conntrack table (ipv4, ipv6)
        # 7-8. a associating flow in egress secgroup table (ipv4, ipv6)
        # 9-10. two ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table (fixed ips)
        # 11. a ingress rule flow (caused by IP addresses represent
        #    remote_group_id changed) in ingress secgroup table (allowes pairs)
        # 12. ingress rules deleted by cookie in ingress secgroup table (ipv4)
        # 13. ingress rules deleted by cookie in ingress secgroup table (ipv6)
        # 14. egress rules deleted by cookie in egress secgroup table (ipv4)
        # 15. egress rules deleted by cookie in egress secgroup table (ipv6)
        # 16. the permit flow in ingress secgroup table
        # 17. the permit flow in egress secgroup table
        self.assertEqual(17, self._get_call_count_of_del_flow())
        self.mock_mod_flow.reset_mock()

        # delete fake security group
        self.controller.delete_secgroup(self.security_group.get_id())

    def test_aggregating_flows_for_addresses(self):
        # initial aggregate addresses list
        aggreate_addresses = cidr_list.CIDRList()
        aggreate_addresses.add_addresses_and_get_changes(['192.168.10.6'])

        # add one address
        added_cidr, deleted_cidr = \
            aggreate_addresses.add_addresses_and_get_changes(['192.168.10.7'])
        expected_new_cidr_list = [netaddr.IPNetwork('192.168.10.6/31')]
        expected_added_cidr = [netaddr.IPNetwork('192.168.10.6/31')]
        expected_deleted_cidr = [netaddr.IPNetwork('192.168.10.6/32')]
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_new_cidr_list)
        self.assertEqual(added_cidr, expected_added_cidr)
        self.assertEqual(deleted_cidr, expected_deleted_cidr)

        # remove one address
        added_cidr, deleted_cidr = \
            aggreate_addresses.remove_addresses_and_get_changes(
                ['192.168.10.7'])
        expected_new_cidr_list = [netaddr.IPNetwork('192.168.10.6/32')]
        expected_added_cidr = [netaddr.IPNetwork('192.168.10.6/32')]
        expected_deleted_cidr = [netaddr.IPNetwork('192.168.10.6/31')]
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_new_cidr_list)
        self.assertEqual(added_cidr, expected_added_cidr)
        self.assertEqual(deleted_cidr, expected_deleted_cidr)

        # update addresses
        added_cidr, deleted_cidr = \
            aggreate_addresses.update_addresses_and_get_changes(
                ['192.168.10.7'], ['192.168.10.6'])
        expected_new_cidr_list = [netaddr.IPNetwork('192.168.10.7/32')]
        expected_added_cidr = [netaddr.IPNetwork('192.168.10.7/32')]
        expected_deleted_cidr = [netaddr.IPNetwork('192.168.10.6/32')]
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_new_cidr_list)
        self.assertEqual(added_cidr, expected_added_cidr)
        self.assertEqual(deleted_cidr, expected_deleted_cidr)

        # create lots of random IPv4 / IPv6 addresses
        lots_addreses = set()
        to_be_removed_addresses = set()
        to_be_removed_addresses2 = set()
        for loop1 in range(1, 6):
            for loop2 in range(0, 100):
                tail = str(random.randint(1, 254))
                address = '1.1.' + str(loop1) + '.' + tail
                lots_addreses.add(address)
                if loop2 < 10:
                    to_be_removed_addresses.add(address)
                elif loop2 < 20:
                    to_be_removed_addresses2.add(address)
        for loop1 in range(1, 3):
            for loop2 in range(0, 100):
                tail = ''.join(random.sample(string.hexdigits, 2))
                address = '::' + str(loop1) + ':' + tail.upper()
                lots_addreses.add(address)
                if loop2 < 10:
                    to_be_removed_addresses.add(address)
                elif loop2 < 20:
                    to_be_removed_addresses2.add(address)
        to_be_removed_addresses2 = (to_be_removed_addresses2 -
                                    to_be_removed_addresses)

        # compare cidr list after adding lots of IPv4 / IPv6 addresses
        aggreate_addresses = cidr_list.CIDRList()
        aggreate_addresses.add_addresses_and_get_changes(lots_addreses)
        expected_addresses_set = netaddr.IPSet(
            [netaddr.IPAddress(item) for item in lots_addreses]
        )
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_addresses_set.iter_cidrs())

        # compare cidr list after removing lots of IPv4 / IPv6 addresses
        aggreate_addresses.remove_addresses_and_get_changes(
            to_be_removed_addresses)
        new_lots_addresses = lots_addreses - to_be_removed_addresses
        expected_addresses_set = netaddr.IPSet(
            [netaddr.IPAddress(item) for item in new_lots_addresses]
        )
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_addresses_set.iter_cidrs())

        # compare cidr list after updating lots of IPv4 / IPv6 addresses
        aggreate_addresses.update_addresses_and_get_changes(
            to_be_removed_addresses, to_be_removed_addresses2)
        new_lots_addresses = lots_addreses - to_be_removed_addresses2
        expected_addresses_set = netaddr.IPSet(
            [netaddr.IPAddress(item) for item in new_lots_addresses]
        )
        self.assertEqual(aggreate_addresses.get_cidr_list(),
                         expected_addresses_set.iter_cidrs())
