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

    def test_broadcast_dhcp_rule(self):
        ovs = objects.OvsTestWarapper()
        flows = ovs.dump()
        for flow in flows:
            if flow['table'] == '9,' and flow['actions'] == 'goto_table:11':
                if ('udp,dl_dst=ff:ff:ff:ff:ff:ff,tp_src=68,tp_dst=67'
                    in flow['match']):
                    return
        self.assertEqual('no_default_dhcp_rule', 0)

    def test_create_update_subnet_with_dhcp(self):
        ovs = objects.OvsTestWarapper()
        flows1 = ovs.dump()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.10.0.0/24',
            'gateway_ip': '10.10.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        subnet2 = self.neutron.create_subnet({'subnet': subnet})
        subnet_id = subnet2['subnet']['id']
        ports = self.neutron.list_ports(network_id=network_id)
        ports = ports['ports']
        dhcp_ip = False
        for port in ports:
            if port['device_owner'] == 'network:dhcp':
                ips = port['fixed_ips']
                for ip in ips:
                    if ip['subnet_id'] == subnet_id:
                        dhcp_ip = ip['ip_address']
        self.assertTrue(dhcp_ip)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows1, dhcp_ip))
        self.assertTrue(self.check_dhcp_rule(flows2, dhcp_ip))
        # change dhcp
        subnet3 = {'enable_dhcp': False}
        self.neutron.update_subnet(subnet_id, {'subnet': subnet3})
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows3, dhcp_ip))
        network.delete()

    def test_create_update_subnet_without_dhcp(self):
        ovs = objects.OvsTestWarapper()
        flows1 = ovs.dump()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.20.0.0/24',
            'gateway_ip': '10.20.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': False}
        subnet2 = self.neutron.create_subnet({'subnet': subnet})
        subnet_id = subnet2['subnet']['id']
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = ovs.dump()
        # change dhcp
        subnet3 = {'enable_dhcp': True}
        self.neutron.update_subnet(subnet_id, {'subnet': subnet3})
        ports = self.neutron.list_ports(network_id=network_id)
        ports = ports['ports']
        dhcp_ip = False
        for port in ports:
            if port['device_owner'] == 'network:dhcp':
                ips = port['fixed_ips']
                for ip in ips:
                    if ip['subnet_id'] == subnet_id:
                        dhcp_ip = ip['ip_address']
        self.assertTrue(dhcp_ip)
        self.assertFalse(self.check_dhcp_rule(flows1, dhcp_ip))
        self.assertFalse(self.check_dhcp_rule(flows2, dhcp_ip))
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = ovs.dump()
        self.assertTrue(self.check_dhcp_rule(flows3, dhcp_ip))
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows4 = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows4, dhcp_ip))

    def test_create_router_interface(self):
        ovs = objects.OvsTestWarapper()
        flows1 = ovs.dump()
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
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
        ports = self.neutron.list_ports(network_id=network_id)
        ports = ports['ports']
        dhcp_ip = False
        for port in ports:
            if port['device_owner'] == 'network:dhcp':
                ips = port['fixed_ips']
                for ip in ips:
                    if ip['subnet_id'] == subnet_id:
                        dhcp_ip = ip['ip_address']
        self.assertTrue(dhcp_ip)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows1, dhcp_ip))
        self.assertTrue(self.check_dhcp_rule(flows2, dhcp_ip))
        #diff = ovs.diff_flows(flows1, flows2)
        #for d in diff:
        #    print d
        self.neutron.remove_interface_router(router_id, body=subnet_msg)
        router.delete()
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = ovs.dump()
        self.assertFalse(self.check_dhcp_rule(flows3, dhcp_ip))
