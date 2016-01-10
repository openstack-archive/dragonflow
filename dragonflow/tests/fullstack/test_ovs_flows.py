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

#from cinderclient.client import client as cinderclient
from novaclient import client as novaclient
from dragonflow.tests.fullstack import test_base

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

#    def test_number_of_flows(self):
#        flows = self._get_ovs_flows()
#        flow_list = flows.split("\n")[1:]
#        flows_count = len(flow_list) - 1
#        self.assertEqual(flows_count,
#                         EXPECTED_NUMBER_OF_FLOWS_AFTER_GATE_DEVSTACK)

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
            # no need for number of packets for now
            #res['packets'] = fs[4].split('=')[1]
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

    def test_create_port(self):
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

    def test_dhcp_port_created(self):
        flows1 = self.get_ovs_flows()
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'network_id': network_id,
            'cidr': '10.1.0.0/24',
            'gateway_ip': '10.1.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        self.neutron.create_subnet({'subnet': subnet})
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        # we must have only one new row
        self.assertEqual(len(diff), 1)
        diff = diff[0]
        self.assertEqual(diff['table'], '9,')
        self.assertEqual(diff['actions'], 'goto_table:11')
        self.assertIn('nw_dst=10.1.0.2', diff['match'])
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        self.assertEqual(flows1, flows3)

    def test_create_router_interface(self):
        flows1 = self.get_ovs_flows()
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        subnet = {'subnets': [{'cidr': '192.168.199.0/24',
                  'ip_version': 4, 'network_id': network_id}]}
        subnets = self.neutron.create_subnet(body=subnet)
        subnet = subnets['subnets'][0]
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet['id']}
        port = self.neutron.add_interface_router(router_id, body=subnet_msg)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        self.assertEqual(len(diff), 3)
        self.assertEqual([diff[0]['table'], diff[1]['table'], diff[2]['table']], ['9,','10,','20,'])
        self.assertIn('tp_src=68,tp_dst=67', diff[0]['match'])
        self.assertIn('arp', diff[1]['match'])
        self.assertIn('nw_dst=192.168.199.1', diff[2]['match'])
        self.assertEqual(['goto_table:11', 'goto_table:64'], [diff[0]['actions'], diff[2]['actions']])
        self.assertIn('IN_PORT', diff[1]['actions'])
        router.delete()
        network.delete()
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])

    def test_simple_private_vm(self):
        flows1 = self.get_ovs_flows()
        creds = test_base.credentials()
        auth_url = creds['auth_url'] + "/v2.0"
        nova = novaclient.Client('2', creds['username'], creds['password'], 'demo', auth_url)
        image = nova.images.find(name="cirros-0.3.4-x86_64-uec")
        self.assertIsNotNone(image)
        flavor = nova.flavors.find(name="m1.tiny")
        self.assertIsNotNone(flavor) 
        network = nova.networks.find(label='private')
        self.assertIsNotNone(network)
        nics = [{'net-id': network.id}]
        server = nova.servers.create(name = 'test', image = image.id, flavor = flavor.id, nics = nics)
        self.assertIsNotNone(server)
        # check vm status here !
        time.sleep(DEFAULT_CMD_TIMEOUT*2)
        flows2 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows2)
        self.assertEqual(len(diff), 6)
        self.assertEqual( [diff[0]['table'], diff[1]['table'], diff[2]['table'], diff[3]['table'], diff[4]['table'], diff[5]['table']], ['0,','0,','11,','17,','17,','64,'])
        self.assertIn('reg7=', diff[5]['match'])
        self.assertIn('output:', diff[5]['actions'])
        m = re.search('reg7=(0x[0-9a-fA-F]+)', diff[5]['match'])
        tunnel_id = m.group(1)
        m = re.search('output:(\d+)', diff[5]['actions'])
        vm_port_id = m.group(1)
        self.assertIn('in_port='+vm_port_id, diff[0]['match'])
        self.assertIn('set_field:'+tunnel_id+'->reg6', diff[0]['actions'])
        self.assertIn('tun_id='+tunnel_id, diff[1]['match'])
        self.assertIn('output:'+vm_port_id, diff[1]['actions'])
        self.assertIn('in_port='+vm_port_id, diff[2]['match'])
        self.assertIn('CONTROLLER:', diff[2]['actions'])
        self.assertIn('set_field:'+tunnel_id+'->reg7,goto_table:64', diff[3]['actions'])
        self.assertIn('dl_dst=01:00:00:00:00:00/01:00:00:00:00:00', diff[4]['match'])
        self.assertIn('set_field:'+tunnel_id+'->reg7,resubmit(,64)', diff[4]['actions'])
        for d in diff:
            print d
        nova.servers.delete(server)
        time.sleep(DEFAULT_CMD_TIMEOUT)
        flows3 = self.get_ovs_flows()
        diff = self._diff_flows(flows1, flows3)
        self.assertEqual(diff, [])
