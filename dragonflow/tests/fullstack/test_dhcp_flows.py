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

from dragonflow.tests.common import utils
from dragonflow.tests.fullstack import test_base
from dragonflow.tests.fullstack import test_objects as objects
import time


DEFAULT_CMD_TIMEOUT = 5


class TestOVSFlowsForDHCP(test_base.DFTestBase):

    def setUp(self):
        super(TestOVSFlowsForDHCP, self).setUp()

    def check_dhcp_rule(self, flows, dhcp_srv):
        for flow in flows:
            if flow['table'] == '9,' and flow['actions'] == 'goto_table:11':
                if ('nw_dst=' + dhcp_srv + ',tp_src=68,tp_dst=67'
                    in flow['match']):
                    return True
        return False

    def get_dhcp_ip(self, network_id, subnet_id):
        ports = self.neutron.list_ports(network_id=network_id)
        ports = ports['ports']
        for port in ports:
            if port['device_owner'] == 'network:dhcp':
                ips = port['fixed_ips']
                for ip in ips:
                    if ip['subnet_id'] == subnet_id:
                        return ip['ip_address']

    def test_broadcast_dhcp_rule(self):
        found_dhcp_cast_flow = False
        ovs = utils.OvsFlowsParser()
        flows = ovs.dump()
        for flow in flows:
            if flow['table'] == '9,' and flow['actions'] == 'goto_table:11':
                if ('udp,dl_dst=ff:ff:ff:ff:ff:ff,tp_src=68,tp_dst=67'
                    in flow['match']):
                    found_dhcp_cast_flow = True
                    break
        self.assertTrue(found_dhcp_cast_flow)

    def test_create_update_subnet_with_dhcp(self):
        ovs = utils.OvsFlowsParser()
        flows_before_change = ovs.dump()
        network = self.store(objects.NetworkTestObj(self.neutron, self.nb_api))
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.10.0.0/24',
            'gateway_ip': '10.10.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        subnet = self.neutron.create_subnet({'subnet': subnet})
        subnet_id = subnet['subnet']['id']
        dhcp_ip = self.get_dhcp_ip(network_id, subnet_id)
        self.assertIsNotNone(dhcp_ip)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows_after_change = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows_before_change, dhcp_ip))
        self.assertTrue(self.check_dhcp_rule(flows_after_change, dhcp_ip))
        # change dhcp
        updated_subnet = {'enable_dhcp': False}
        self.neutron.update_subnet(subnet_id, {'subnet': updated_subnet})
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows_after_update = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows_after_update, dhcp_ip))
        network.delete()

    def test_create_update_subnet_without_dhcp(self):
        ovs = utils.OvsFlowsParser()
        flows_before_change = ovs.dump()
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
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows_after_change = ovs.dump()
        # change dhcp
        updated_subnet = {'enable_dhcp': True}
        self.neutron.update_subnet(subnet_id, {'subnet': updated_subnet})
        dhcp_ip = self.get_dhcp_ip(network_id, subnet_id)
        self.assertIsNotNone(dhcp_ip)
        self.assertFalse(self.check_dhcp_rule(flows_before_change, dhcp_ip))
        self.assertFalse(self.check_dhcp_rule(flows_after_change, dhcp_ip))
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows_after_update = ovs.dump()
        self.assertTrue(self.check_dhcp_rule(flows_after_update, dhcp_ip))
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows_after_cleanup = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows_after_cleanup, dhcp_ip))

    def test_create_router_interface(self):
        ovs = utils.OvsFlowsParser()
        flows_before_change = ovs.dump()
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
        self.neutron.add_interface_router(router_id, body=subnet_msg)
        dhcp_ip = self.get_dhcp_ip(network_id, subnet_id)
        self.assertIsNotNone(dhcp_ip)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows_after_change = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows_before_change, dhcp_ip))
        self.assertTrue(self.check_dhcp_rule(flows_after_change, dhcp_ip))
        self.neutron.remove_interface_router(router_id, body=subnet_msg)
        router.delete()
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows_after_cleanup = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows_after_cleanup, dhcp_ip))
