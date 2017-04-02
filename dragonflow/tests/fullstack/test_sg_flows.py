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

import time

from neutron_lib import constants as n_const
from oslo_log import log

from dragonflow.controller.common import constants as const
from dragonflow.tests.common import constants as test_const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects

LOG = log.getLogger(__name__)


class TestOVSFlowsForSecurityGroup(test_base.DFTestBase):

    def _is_skip_flow(self, flow, direction):
        if direction == 'ingress':
            table = const.INGRESS_CONNTRACK_TABLE
            goto_table = const.INGRESS_DISPATCH_TABLE
        else:
            table = const.EGRESS_CONNTRACK_TABLE
            goto_table = const.SERVICES_CLASSIFICATION_TABLE

        if (flow['table'] == str(table)) and \
                (flow['priority'] == str(const.PRIORITY_DEFAULT)) and \
                (flow['actions'] == ('goto_table:' + str(goto_table))):
            return True

        return False

    def _is_default_drop_flow(self, flow, direction):
        if direction == 'ingress':
            table = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table = const.EGRESS_SECURITY_GROUP_TABLE

        if (flow['table'] == str(table)) and \
                (flow['priority'] == str(const.PRIORITY_DEFAULT)) and \
                (flow['actions'] == 'drop'):
            return True

        return False

    def _is_conntrack_pass_flow(self, flow, direction, ct_state_match):
        if direction == 'ingress':
            table = const.INGRESS_SECURITY_GROUP_TABLE
            goto_table = const.INGRESS_DISPATCH_TABLE
        else:
            table = const.EGRESS_SECURITY_GROUP_TABLE
            goto_table = const.SERVICES_CLASSIFICATION_TABLE

        if (flow['table'] == str(table)) and \
                (flow['priority'] == str(const.PRIORITY_CT_STATE)) and \
                (ct_state_match in flow['match']) and \
                (flow['actions'] == ('goto_table:' + str(goto_table))):
            return True

        return False

    def _is_conntrack_established_pass_flow(self, flow, direction):
        return self._is_conntrack_pass_flow(
            flow=flow, direction=direction,
            ct_state_match='-new+est-rel-inv+trk')

    def _is_conntrack_relative_not_new_pass_flow(self, flow, direction):
        return self._is_conntrack_pass_flow(
            flow=flow, direction=direction,
            ct_state_match='-new+rel-inv+trk')

    def _is_conntrack_relative_new_pass_flow(self, flow, direction):
        if direction == 'ingress':
            table = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table = const.EGRESS_SECURITY_GROUP_TABLE

        if (flow['table'] == str(table)) and \
                (flow['priority'] == str(const.PRIORITY_CT_STATE)) and \
                ('+new+rel-inv+trk' in flow['match']) and \
                ('ct(commit,table' in flow['actions']):
            return True

        return False

    def _is_conntrack_invalid_drop_flow(self, flow, direction):
        if direction == 'ingress':
            table = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table = const.EGRESS_SECURITY_GROUP_TABLE

        if (flow['table'] == str(table)) and \
                (flow['priority'] == str(const.PRIORITY_CT_STATE)) and \
                ('ct_state=+inv+trk' in flow['match']) and \
                (flow['actions'] == 'drop'):
            return True

        return False

    def _is_associating_flow(self, flow, direction, unique_key):
        if direction == 'ingress':
            match = 'reg7=' + str(unique_key)
            table = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            match = 'reg6=' + str(unique_key)
            table = const.EGRESS_SECURITY_GROUP_TABLE

        if (flow['table'] == str(table)) and \
                ('ct_state=+new-est-rel-inv+trk' in flow['match']) and \
                (match in flow['match']) and \
                ('conjunction(' in flow['actions']) and \
                (',1/2)' in flow['actions']):
            return True

        return False

    def _find_associating_flows(self, flows, unique_key):
        ingress_associating_flow = None
        egress_associating_flow = None
        for flow in flows:
            if self._is_associating_flow(flow=flow, direction='ingress',
                                         unique_key=unique_key):
                ingress_associating_flow = flow
            elif self._is_associating_flow(flow=flow, direction='egress',
                                           unique_key=unique_key):
                egress_associating_flow = flow

        return ingress_associating_flow, egress_associating_flow

    def _is_rule_flow(self, flow, direction):
        if direction == 'ingress':
            table = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table = const.EGRESS_SECURITY_GROUP_TABLE

        if (flow['table'] == str(table)) and \
                ('conjunction(' in flow['actions']) and \
                (',2/2' in flow['actions']):
            return True
        return False

    def _is_permit_flow(self, flow, direction):
        if direction == 'ingress':
            table = const.INGRESS_SECURITY_GROUP_TABLE
        else:
            table = const.EGRESS_SECURITY_GROUP_TABLE

        if (flow['table'] == str(table)) and \
                ('conj_id=' in flow['match']) and \
                ('ct(commit,table' in flow['actions']):
            return True
        return False

    def _check_rule_flows(self, flows, expected_ingress_rule_match,
                          expected_egress_rule_match, expect):
        ingress_rule_flow_check = not expect
        egress_rule_flow_check = not expect
        ingress_permit_flow_check = not expect
        egress_permit_flow_check = not expect

        for flow in flows:
            if self._is_rule_flow(flow, 'ingress') and \
                    (expected_ingress_rule_match in flow['match']):
                ingress_rule_flow_check = expect
            elif self._is_rule_flow(flow, 'egress') and \
                    (expected_egress_rule_match in flow['match']):
                egress_rule_flow_check = expect
            elif self._is_permit_flow(flow, 'ingress'):
                ingress_permit_flow_check = expect
            elif self._is_permit_flow(flow, 'egress'):
                egress_permit_flow_check = expect

        self.assertTrue(ingress_rule_flow_check)
        self.assertTrue(egress_rule_flow_check)
        self.assertTrue(ingress_permit_flow_check)
        self.assertTrue(egress_permit_flow_check)

    def test_default_flows(self):
        found_ingress_skip_flow = False
        found_egress_skip_flow = False
        found_ingress_default_drop_flow = False
        found_egress_default_drop_flow = False
        found_ingress_conntrack_established_pass_flow = False
        found_egress_conntrack_established_pass_flow = False
        found_ingress_conntrack_relative_not_new_pass_flow = False
        found_egress_conntrack_relative_not_new_pass_flow = False
        found_ingress_conntrack_relative_new_pass_flow = False
        found_egress_conntrack_relative_new_pass_flow = False
        found_ingress_conntrack_invalied_drop_flow = False
        found_egress_conntrack_invalied_drop_flow = False

        ovs = utils.OvsFlowsParser()
        flows = ovs.dump(self.integration_bridge)
        for flow in flows:
            if self._is_skip_flow(flow=flow, direction='ingress'):
                found_ingress_skip_flow = True
            elif self._is_skip_flow(flow=flow, direction='egress'):
                found_egress_skip_flow = True
            elif self._is_default_drop_flow(flow=flow, direction='ingress'):
                found_ingress_default_drop_flow = True
            elif self._is_default_drop_flow(flow=flow, direction='egress'):
                found_egress_default_drop_flow = True
            elif self._is_conntrack_established_pass_flow(flow=flow,
                                                          direction='ingress'):
                found_ingress_conntrack_established_pass_flow = True
            elif self._is_conntrack_established_pass_flow(flow=flow,
                                                          direction='egress'):
                found_egress_conntrack_established_pass_flow = True
            elif self._is_conntrack_relative_not_new_pass_flow(
                    flow=flow, direction='ingress'):
                found_ingress_conntrack_relative_not_new_pass_flow = True
            elif self._is_conntrack_relative_not_new_pass_flow(
                    flow=flow, direction='egress'):
                found_egress_conntrack_relative_not_new_pass_flow = True
            elif self._is_conntrack_relative_new_pass_flow(
                    flow=flow, direction='ingress'):
                found_ingress_conntrack_relative_new_pass_flow = True
            elif self._is_conntrack_relative_new_pass_flow(
                    flow=flow, direction='egress'):
                found_egress_conntrack_relative_new_pass_flow = True
            elif self._is_conntrack_invalid_drop_flow(flow=flow,
                                                      direction='ingress'):
                found_ingress_conntrack_invalied_drop_flow = True
            elif self._is_conntrack_invalid_drop_flow(flow=flow,
                                                      direction='egress'):
                found_egress_conntrack_invalied_drop_flow = True

        LOG.info("default flows are: %s",
                 ovs.get_ovs_flows(self.integration_bridge))

        self.assertTrue(found_ingress_skip_flow)
        self.assertTrue(found_egress_skip_flow)
        self.assertTrue(found_ingress_default_drop_flow)
        self.assertTrue(found_egress_default_drop_flow)
        self.assertTrue(found_ingress_conntrack_established_pass_flow)
        self.assertTrue(found_egress_conntrack_established_pass_flow)
        self.assertTrue(found_ingress_conntrack_relative_not_new_pass_flow)
        self.assertTrue(found_egress_conntrack_relative_not_new_pass_flow)
        self.assertTrue(found_ingress_conntrack_relative_new_pass_flow)
        self.assertTrue(found_egress_conntrack_relative_new_pass_flow)
        self.assertTrue(found_ingress_conntrack_invalied_drop_flow)
        self.assertTrue(found_egress_conntrack_invalied_drop_flow)

    def test_associating_flows(self):

        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        self.assertTrue(network.exists())

        subnet_info = {'network_id': network_id,
                       'cidr': '192.168.123.0/24',
                       'gateway_ip': '192.168.123.1',
                       'ip_version': 4,
                       'name': 'test_subnet1',
                       'enable_dhcp': True}
        subnet = self.store(objects.SubnetTestObj(self.neutron,
                                                  self.nb_api,
                                                  network_id=network_id))
        subnet.create(subnet_info)
        self.assertTrue(subnet.exists())

        security_group = self.store(objects.SecGroupTestObj(
            self.neutron,
            self.nb_api))
        security_group_id = security_group.create()
        self.assertTrue(security_group.exists())

        vm = self.store(objects.VMTestObj(self, self.neutron))
        vm.create(network=network, security_groups=[security_group_id])

        addresses = vm.server.addresses['mynetwork']
        self.assertIsNotNone(addresses)
        ip = addresses[0]['addr']
        self.assertIsNotNone(ip)
        mac = addresses[0]['OS-EXT-IPS-MAC:mac_addr']
        self.assertIsNotNone(mac)
        port = utils.wait_until_is_and_return(
            lambda: utils.get_vm_port(self.nb_api, ip, mac),
            exception=Exception('No port assigned to VM')
        )
        unique_key = port.get_unique_key()
        unique_key_hex = hex(unique_key)

        of_port = self.vswitch_api.get_port_ofport_by_id(port.get_id())
        self.assertIsNotNone(of_port)

        ovs = utils.OvsFlowsParser()
        flows_after_change = ovs.dump(self.integration_bridge)

        # Check if the associating flows were installed.
        ingress_associating_flow, egress_associating_flow = \
            self._find_associating_flows(flows_after_change, unique_key_hex)

        LOG.info("flows after associating a port and a security group"
                 " are: %s",
                 ovs.get_ovs_flows(self.integration_bridge))

        self.assertIsNotNone(ingress_associating_flow)
        self.assertIsNotNone(egress_associating_flow)

        vm.close()

        time.sleep(test_const.DEFAULT_RESOURCE_READY_TIMEOUT)
        flows_after_update = ovs.dump(self.integration_bridge)

        # Check if the associating flows were removed.
        ingress_associating_flow, egress_associating_flow = \
            self._find_associating_flows(flows_after_update, unique_key_hex)

        self.assertIsNone(ingress_associating_flow)
        self.assertIsNone(egress_associating_flow)

    def test_rule_flows(self):

        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        self.assertTrue(network.exists())

        subnet_info = {'network_id': network_id,
                       'cidr': '192.168.124.0/24',
                       'gateway_ip': '192.168.124.1',
                       'ip_version': 4,
                       'name': 'test_subnet4',
                       'enable_dhcp': True}
        subnet = self.store(objects.SubnetTestObj(self.neutron,
                                                  self.nb_api,
                                                  network_id=network_id))
        subnet.create(subnet_info)

        security_group = self.store(objects.SecGroupTestObj(
            self.neutron,
            self.nb_api))
        security_group_id = security_group.create()
        self.assertTrue(security_group.exists())

        ingress_rule_info = {'ethertype': 'IPv4',
                             'direction': 'ingress',
                             'protocol': 'tcp',
                             'port_range_min': '80',
                             'port_range_max': '81',
                             'remote_ip_prefix': '192.168.124.0/24'}
        ingress_rule_id = security_group.rule_create(secrule=ingress_rule_info)
        self.assertTrue(security_group.rule_exists(ingress_rule_id))

        egress_rule_info = {'ethertype': 'IPv4',
                            'direction': 'egress',
                            'protocol': str(n_const.PROTO_NUM_UDP),
                            'port_range_min': '53',
                            'port_range_max': '53',
                            'remote_group_id': security_group_id}
        egress_rule_id = security_group.rule_create(secrule=egress_rule_info)
        self.assertTrue(security_group.rule_exists(egress_rule_id))

        vm1 = self.store(objects.VMTestObj(self, self.neutron))
        vm1.create(network=network, security_groups=[security_group_id],
                   net_address='192.168.124.8')
        vm2 = self.store(objects.VMTestObj(self, self.neutron))
        vm2.create(network=network, security_groups=[security_group_id],
                   net_address='192.168.124.9')

        time.sleep(test_const.DEFAULT_RESOURCE_READY_TIMEOUT)

        ovs = utils.OvsFlowsParser()
        flows = ovs.dump(self.integration_bridge)

        LOG.info("flows after adding rules are: %s",
                 ovs.get_ovs_flows(self.integration_bridge))

        # Check if the rule flows were installed.
        expected_ingress_rule_match = \
            "tcp,nw_src=192.168.124.0/24,tp_dst=0x50/0xfffe"
        expected_egress_rule_match = \
            "udp,nw_dst=192.168.124.8/31,tp_dst=53"
        self._check_rule_flows(flows, expected_ingress_rule_match,
                               expected_egress_rule_match, True)

        vm1.close()
        vm2.close()

        # We can't guarantee that all rule flows have been deleted because
        # those rule flows may be installed in other test cases for all
        # test cases are running synchronously.

        # time.sleep(test_const.DEFAULT_RESOURCE_READY_TIMEOUT)
        # flows_after_update = ovs.dump(self.integration_bridge)
        # self._check_rule_flows(flows_after_update,
        #                        expected_ingress_rule_match,
        #                        expected_egress_rule_match, False)
