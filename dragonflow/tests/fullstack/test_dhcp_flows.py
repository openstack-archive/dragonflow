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

from dragonflow.controller.common import constants
from dragonflow.tests.common import constants as const
from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects


class TestOVSFlowsForDHCP(test_base.DFTestBase):

    def setUp(self):
        super(TestOVSFlowsForDHCP, self).setUp()

    def get_dhcp_ip(self, network_id, subnet_id):
        ports = self.neutron.list_ports(network_id=network_id)
        ports = ports['ports']
        for port in ports:
            if port['device_owner'] == 'network:dhcp':
                ips = port['fixed_ips']
                for ip in ips:
                    if ip['subnet_id'] == subnet_id:
                        return ip['ip_address']
        return None

    def test_broadcast_dhcp_rule(self):
        found_dhcp_cast_flow = False
        ovs = utils.OvsFlowsParser()
        flows = ovs.dump(self.integration_bridge)
        goto_dhcp = 'goto_table:' + str(constants.DHCP_TABLE)
        dhcp_ports = ',tp_src=' + str(constants.DHCP_CLIENT_PORT) + \
                     ',tp_dst=' + str(constants.DHCP_SERVER_PORT)
        for flow in flows:
            if (flow['table'] == str(constants.SERVICES_CLASSIFICATION_TABLE)
                and flow['actions'] == goto_dhcp):
                if ('udp,dl_dst=' + constants.BROADCAST_MAC + dhcp_ports
                    in flow['match']):
                    found_dhcp_cast_flow = True
                    break
        self.assertTrue(found_dhcp_cast_flow)

    def test_create_update_subnet_with_dhcp(self):
        ovs = utils.OvsFlowsParser()
        flows_before_change = ovs.dump(self.integration_bridge)
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.10.254.0/24',
            'gateway_ip': '10.10.254.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        subnet = self.neutron.create_subnet({'subnet': subnet})
        subnet_id = subnet['subnet']['id']
        dhcp_ip = utils.wait_until_is_and_return(
            lambda: self.get_dhcp_ip(network_id, subnet_id),
            exception=Exception('DHCP IP was not generated')
        )
        self.assertFalse(utils.check_dhcp_ip_rule(
            flows_before_change, dhcp_ip))
        utils.wait_until_true(
            lambda: utils.check_dhcp_ip_rule(ovs.dump(self.integration_bridge),
                                         dhcp_ip),
            exception=Exception('DHCP ip was not found in OpenFlow rules'),
            timeout=5
        )
        # change dhcp
        updated_subnet = {'enable_dhcp': False}
        self.neutron.update_subnet(subnet_id, {'subnet': updated_subnet})
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        flows_after_update = ovs.dump(self.integration_bridge)
        self.assertFalse(utils.check_dhcp_ip_rule(flows_after_update, dhcp_ip))
        network.close()

    def test_create_update_subnet_without_dhcp(self):
        ovs = utils.OvsFlowsParser()
        flows_before_change = ovs.dump(self.integration_bridge)
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.20.0.0/24',
            'gateway_ip': '10.20.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': False}
        subnet = self.neutron.create_subnet({'subnet': subnet})
        subnet_id = subnet['subnet']['id']
        time.sleep(const.DEFAULT_CMD_TIMEOUT)
        flows_after_change = ovs.dump(self.integration_bridge)
        # change dhcp
        updated_subnet = {'enable_dhcp': True}
        self.neutron.update_subnet(subnet_id, {'subnet': updated_subnet})
        dhcp_ip = utils.wait_until_is_and_return(
            lambda: self.get_dhcp_ip(network_id, subnet_id),
            exception=Exception('DHCP IP was not generated')
        )
        self.assertFalse(utils.check_dhcp_ip_rule(
            flows_before_change, dhcp_ip))
        self.assertFalse(utils.check_dhcp_ip_rule(flows_after_change, dhcp_ip))
        utils.wait_until_true(
            lambda: utils.check_dhcp_ip_rule(ovs.dump(self.integration_bridge),
                                         dhcp_ip),
            exception=Exception('DHCP ip was not found in OpenFlow rules'),
            timeout=5
        )
        network.close()
        utils.wait_until_none(
            lambda: utils.check_dhcp_ip_rule(ovs.dump(self.integration_bridge),
                                         dhcp_ip),
            exception=Exception('DHCP IP was not removed from OpenFlow rules'),
            timeout=30
        )

    def test_create_router_interface(self):
        ovs = utils.OvsFlowsParser()
        flows_before_change = ovs.dump(self.integration_bridge)
        router = self.store(objects.RouterTestObj(self.neutron, self.nb_api))
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.30.0.0/24',
            'gateway_ip': '10.30.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        subnet = self.neutron.create_subnet({'subnet': subnet})
        subnet_id = subnet['subnet']['id']
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet_id}
        time.sleep(const.DEFAULT_RESOURCE_READY_TIMEOUT)
        self.neutron.add_interface_router(router_id, body=subnet_msg)
        dhcp_ip = utils.wait_until_is_and_return(
            lambda: self.get_dhcp_ip(network_id, subnet_id),
            exception=Exception('DHCP IP was not generated')
        )
        flows_after_change = ovs.dump(self.integration_bridge)
        self.assertFalse(utils.check_dhcp_ip_rule(
            flows_before_change, dhcp_ip))
        self.assertTrue(utils.check_dhcp_ip_rule(flows_after_change, dhcp_ip))
        self.neutron.remove_interface_router(router_id, body=subnet_msg)
        router.close()
        network.close()
        utils.wait_until_none(
            lambda: utils.check_dhcp_ip_rule(ovs.dump(self.integration_bridge),
                                         dhcp_ip),
            exception=Exception('DHCP IP was not removed from OpenFlow rules'),
            timeout=30
        )
