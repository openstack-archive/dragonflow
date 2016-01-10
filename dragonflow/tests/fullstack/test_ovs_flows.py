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
from neutron.agent.common import utils
import re
import time

EXPECTED_NUMBER_OF_FLOWS_AFTER_GATE_DEVSTACK = 26
DEFAULT_CMD_TIMEOUT = 5


class TestOVSFlows(test_base.DFTestBase):

    def setUp(self):
        super(TestOVSFlows, self).setUp()

    def _get_ovs_flows(self):
        full_args = ["ovs-ofctl", "dump-flows", 'br-int', '-O Openflow13']
        flows = utils.execute(full_args, run_as_root=True,
                              process_input=None)
        return flows

    def _parse_ovs_flows(self, flows):
        flow_list = flows.split("\n")[1:]
        flows_as_dicts = []
        for flow in flow_list:
            if len(flow) == 0:
                continue
            fs = flow.split(' ')
            res = {}
            res['table'] = fs[3].split('=')[1]
            res['match'] = fs[-2]
            res['actions'] = fs[-1].split('=')[1]
            res['cookie'] = fs[1].split('=')[1]
            m = re.search('priority=(\d+)', res['match'])
            if m:
                res['priority'] = m.group(1)
                res['match'] = re.sub(r'priority=(\d+),?', '', res['match'])
            flows_as_dicts.append(res)
        return flows_as_dicts

    def _diff_flows(self, list1, list2):
        result = [v for v in list2 if v not in list1]
        return result

    def get_ovs_flows(self):
        flows = self._get_ovs_flows()
        return self._parse_ovs_flows(flows)

    def check_dhcp_rule(self, flows, dhcp_srv):
        for flow in flows:
            if flow['table'] == '9,' and flow['actions'] =='goto_table:11':
                if 'nw_dst='+dhcp_srv+',tp_src=68,tp_dst=67' in flow['match']:
                    print("found dhcp rule")
                    return True
        print("not found dhcp rule")
        return False

    def test_create_delete_network(self):
        flows1 = self.get_ovs_flows()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network.create()
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        # nothing should be changed on not-attached port creation
        self.assertEqual(diff, [])
        network.delete()
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        # nothing should be changed when port is delated
        self.assertEqual(diff, [])

    def test_create_delete_port(self):
        flows1 = self.get_ovs_flows()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        port = {'admin_state_up': True, 'name': 'port1',
                'network_id': network_id}
        port = self.neutron.create_port(body={'port': port})
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        self.assertEqual(diff, [])
        self.neutron.delete_port(port['port']['id'])
        network.delete()
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])

    def test_create_delete_subnet(self):
        flows1 = self.get_ovs_flows()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'subnet': {'cidr': '192.168.199.0/24',
                  'gateway_ip': '192.168.199.1',
                  'enable_dhcp': False,
                  'ip_version': 4, 'network_id': network_id}}
        subnet = self.neutron.create_subnet(body=subnet)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        self.assertEqual(diff, [])
        network.delete()
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])

    def test_create_delete_router(self):
        flows1 = self.get_ovs_flows()
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        router.create()
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        self.assertEqual(diff, [])
        router.delete()
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])

    def test_dhcp_port_create(self):
        flows1 = self.get_ovs_flows()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.1.0.0/24',
            'gateway_ip': '10.1.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        subnet2 = self.neutron.create_subnet({'subnet': subnet})
        #print(subnet2)
        subnet_id = subnet2['subnet']['id']
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = self.get_ovs_flows()
        self.assertTrue(self.check_dhcp_rule(flows2, '10.1.0.2'))
        # change dhcp
        subnet3 = {'enable_dhcp': False}
        self.neutron.update_subnet(subnet_id, {'subnet': subnet3})
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        self.assertFalse(self.check_dhcp_rule(flows3, '10.1.0.2'))
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows4 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows4)
        self.assertEqual(diff, [])

    def test_port_create_without_dhcp(self):
        flows1 = self.get_ovs_flows()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.1.0.0/24',
            'gateway_ip': '10.1.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': False}
        subnet2 = self.neutron.create_subnet({'subnet': subnet})
        subnet_id = subnet2['subnet']['id']
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = self.get_ovs_flows()
        self.assertFalse(self.check_dhcp_rule(flows2, '10.1.0.2'))
        # change dhcp
        subnet3 = {'enable_dhcp': True}
        self.neutron.update_subnet(subnet_id, {'subnet': subnet3})
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        self.assertTrue(self.check_dhcp_rule(flows3, '10.1.0.2'))
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows4 = self.get_ovs_flows()
        self.assertFalse(self.check_dhcp_rule(flows4, '10.1.0.2'))
        diff = self._diff_flows(flows1, flows4)
        self.assertEqual(diff, [])

    def test_create_router_interface(self):
        flows1 = self.get_ovs_flows()
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'subnet': {'cidr': '192.168.199.0/24',
                  'ip_version': 4, 'network_id': network_id}}
        subnet = self.neutron.create_subnet(body=subnet)
        subnet_id = subnet['subnet']['id']
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet_id}
        self.neutron.add_interface_router(router_id, body=subnet_msg)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        for d in diff:
            print d
        self.assertEqual(len(diff), 3)
        self.assertEqual([diff[0]['table'], diff[1]['table'],
                   diff[2]['table']], ['9,', '10,', '20,'])
        self.assertIn('tp_src=68,tp_dst=67', diff[0]['match'])
        self.assertIn('arp', diff[1]['match'])
        self.assertIn('nw_dst=192.168.199.1', diff[2]['match'])
        self.assertEqual(['goto_table:11', 'goto_table:64'],
                   [diff[0]['actions'], diff[2]['actions']])
        self.assertIn('IN_PORT', diff[1]['actions'])
        self.neutron.remove_interface_router(router_id, body=subnet_msg)
        router.delete()
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])

    def test_alter_subnet_gw(self):
        flows1 = self.get_ovs_flows()
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'subnet': {'cidr': '192.168.199.0/24',
                  'gateway_ip': '192.168.199.1',
                  'enable_dhcp': False,
                  'ip_version': 4, 'network_id': network_id}}
        subnet = self.neutron.create_subnet(body=subnet)
        return
        subnet_id = subnet['subnet']['id']
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet_id}
        self.neutron.add_interface_router(router_id, body=subnet_msg)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        for d in diff:
            print d
        print("-------------------------------")
        subnet3 = {'gateway_ip': '192.168.199.138'}
        self.neutron.update_subnet(subnet['id'], {'subnet': subnet3})
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows2, flows3)
        for d in diff:
            print d

        self.assertEqual(len(diff), 2)
        self.assertEqual([diff[0]['table'], diff[1]['table']],
                         ['10,', '20,'])
        self.assertIn('arp', diff[0]['match'])
        self.assertIn('set_field:192.168.199.1->arp_spa', diff[0]['actions'])
        self.assertIn('nw_dst=192.168.199.1', diff[1]['match'])
        self.assertEqual('goto_table:64', diff[1]['actions'])
        self.neutron.remove_interface_router(router_id, body=subnet_msg)
        router.delete()
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])

    def test_simple_private_vm(self):
        flows1 = self.get_ovs_flows()
        vm = objects.VMTestWrapper(self)
        vm.create()
        self.assertTrue(vm.exists())
        time.sleep(DEFAULT_CMD_TIMEOUT)
        #print(vm.dump())
        #vm.shell()
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        #for d in diff:
        #    print d
        self.assertEqual(len(diff), 6)
        self.assertEqual([diff[0]['table'], diff[1]['table'],
                          diff[2]['table'], diff[3]['table'],
                          diff[4]['table'], diff[5]['table']],
                         ['0,', '0,', '11,', '17,', '17,', '64,'])
        self.assertIn('reg7=', diff[5]['match'])
        self.assertIn('output:', diff[5]['actions'])
        m = re.search('reg7=(0x[0-9a-fA-F]+)', diff[5]['match'])
        tunnel_id = m.group(1)
        m = re.search('output:(\d+)', diff[5]['actions'])
        vm_port_id = m.group(1)
        self.assertIn('in_port=' + vm_port_id, diff[0]['match'])
        self.assertIn('set_field:' + tunnel_id + '->reg6', diff[0]['actions'])
        self.assertIn('tun_id=' + tunnel_id, diff[1]['match'])
        self.assertIn('output:' + vm_port_id, diff[1]['actions'])
        self.assertIn('in_port=' + vm_port_id, diff[2]['match'])
        self.assertIn('CONTROLLER:', diff[2]['actions'])
        self.assertIn('set_field:' + tunnel_id + '->reg7,goto_table:64',
                      diff[3]['actions'])
        self.assertIn('dl_dst=01:00:00:00:00:00/01:00:00:00:00:00',
                      diff[4]['match'])
        self.assertIn('set_field:' + tunnel_id + '->reg7,resubmit(,64)',
                      diff[4]['actions'])
        vm.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT * 2)
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])

    def test_vm_ping(self):
        vm = objects.VMTestWrapper(self)
        cmd = "#!/bin/bash\n"
        cmd = cmd + "echo 'Hello World'\n"
        cmd = cmd + "ping 10.0.0.1\n"
        cmd = cmd + "exit 0\n"
        vm.create(cmd)
        self.assertTrue(vm.exists())
        time.sleep(DEFAULT_CMD_TIMEOUT)
        vm.delete()
