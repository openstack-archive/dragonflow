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

import os_client_config
from oslo_config import cfg
from oslo_utils import importutils

from neutron.agent.common import utils
from neutron.common import config as common_config
from neutron.tests import base
from neutronclient.neutron import client

from dragonflow.common import common_params
from dragonflow.db import api_nb
import test_objects as objects

cfg.CONF.register_opts(common_params.df_opts, 'df')

EXPECTED_NUMBER_OF_FLOWS_AFTER_GATE_DEVSTACK = 26


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)


def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()


class TestNeutronAPIandDB(base.BaseTestCase):

    def setUp(self):
        super(TestNeutronAPIandDB, self).setUp()
        creds = credentials()
        tenant_name = creds['project_name']
        auth_url = creds['auth_url'] + "/v2.0"
        self.neutron = client.Client('2.0', username=creds['username'],
             password=creds['password'], auth_url=auth_url,
             tenant_name=tenant_name)
        self.neutron.format = 'json'
        common_config.init(['--config-file', '/etc/neutron/neutron.conf'])

        db_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(db_driver_class())
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
            db_port=cfg.CONF.df.remote_db_port)

    def test_create_network(self):
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network.create()
        self.assertTrue(network.exists())
        network.delete()
        self.assertFalse(network.exists())

    def test_dhcp_port_created(self):
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = {'network_id': network_id,
            'cidr': '10.1.0.0/24',
            'gateway_ip': '10.1.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        self.neutron.create_subnet({'subnet': subnet})
        ports = self.nb_api.get_all_logical_ports()
        dhcp_ports_found = 0
        for port in ports:
            if port.get_lswitch_id() == network_id:
                if port.get_device_owner() == 'network:dhcp':
                    dhcp_ports_found += 1
        network.delete()
        self.assertEqual(dhcp_ports_found, 1)
        ports = self.nb_api.get_all_logical_ports()
        dhcp_ports_found = 0
        for port in ports:
            if port.get_lswitch_id() == network_id:
                if port.get_device_owner() == 'network:dhcp':
                    dhcp_ports_found += 1
        self.assertEqual(dhcp_ports_found, 0)

    def test_create_delete_router(self):
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        router.create()
        self.assertTrue(router.exists())
        router.delete()
        self.assertFalse(router.exists())

    def test_create_router_interface(self):
        router = objects.RouterTestWrapper(self.neutron, self.nb_api)
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        subnet = {'subnets': [{'cidr': '192.168.199.0/24',
                  'ip_version': 4, 'network_id': network_id}]}
        subnets = self.neutron.create_subnet(body=subnet)
        subnet = subnets['subnets'][0]
        router_id = router.create()
        self.assertTrue(router.exists())
        subnet_msg = {'subnet_id': subnet['id']}
        port = self.neutron.add_interface_router(router_id, body=subnet_msg)
        port2 = self.nb_api.get_logical_port(port['port_id'])
        self.assertIsNotNone(port2)
        router.delete()
        port2 = self.nb_api.get_logical_port(port['port_id'])
        self.assertIsNone(port2)
        network.delete()
        self.assertFalse(router.exists())
        self.assertFalse(network.exists())

    def test_create_port(self):
        network = objects.NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        self.assertTrue(network.exists())
        port = {'admin_state_up': True, 'name': 'port1',
                'network_id': network_id}
        port = self.neutron.create_port(body={'port': port})
        port2 = self.nb_api.get_logical_port(port['port']['id'])
        self.assertIsNotNone(port2)
        self.assertEqual(network_id, port2.get_lswitch_id())
        self.neutron.delete_port(port['port']['id'])
        port2 = self.nb_api.get_logical_port(port['port']['id'])
        self.assertIsNone(port2)
        network.delete()
        self.assertFalse(network.exists())

    def _get_ovs_flows(self):
        full_args = ["ovs-ofctl", "dump-flows", 'br-int', '-O Openflow13']
        flows = utils.execute(full_args, run_as_root=True,
                              process_input=None)
        return flows

    def test_number_of_flows(self):
        flows = self._get_ovs_flows()
        flow_list = flows.split("\n")[1:]
        flows_count = len(flow_list) - 1
        self.assertEqual(flows_count,
                         EXPECTED_NUMBER_OF_FLOWS_AFTER_GATE_DEVSTACK)

    def _parse_ovs_flows(self):
        flows = self._get_ovs_flows()
        flow_list = flows.split("\n")[1:]
        flows_as_dicts = []
        for flow in flow_list:
            fs = flow.split(' ')
            res = {}
            res['table'] = fs[3].split('=')[1]
            res['match'] = fs[6]
            res['packets'] = fs[4].split('=')[1]
            res['actions'] = fs[7].split('=')[1]
            res['cookie'] = fs[1].split('=')[1]
            flows_as_dicts.append(res)
        return flows_as_dicts

'''
The following tests are for list networks/routers/ports/subnets API.
They require seqential execution because another running test can break them.
To be able to run tests sequentially, testr must be started with
"--concurrency=1" argument. You can do it in tools/pretty_tox.sh file.

Currently it has the following falue:
--testr-args="--concurrency=1 --subunit $TESTRARGS";
'''

'''
Sequential tests
    def test_list_networks(self):
        networks = self.neutron.list_networks()
        networks = networks['networks']
        #print("networks", networks)
        networks2 = list()
        for network in networks:
            networks2.append(network['id'])
        networks2.sort()
        switches = self.nb_api.get_all_logical_switches()
        switches2 = list()
        for switch in switches:
            switches2.append(switch.get_id())
        switches2.sort()
        self.assertEqual(networks2, switches2)

    def test_list_subnets(self):
        subnets = self.neutron.list_subnets(retrieve_all=True)
        subnets = subnets['subnets']
        #print("subnets", subnets)
        subnets2 = list()
        for subnet in subnets:
            subnets2.append(subnet['id'])
        subnets2.sort()
        switches = self.nb_api.get_all_logical_switches()
        subnets3 = list()
        for switch in switches:
            subnets = switch.get_subnets()
            for subnet in subnets:
                subnets3.append(subnet.get_id())
        subnets3.sort()
        self.assertEqual(subnets2, subnets3)

    def test_list_local_ports(self):
        ports = self.neutron.list_ports(retrieve_all=True)
        ports = ports['ports']
        ports2 = list()
        for port in ports:
            if port['binding:host_id'] is not None:
                if port['device_owner'] != 'network:router_gateway':
                    ports2.append(port['id'])
        ports2.sort()
        lports = self.nb_api.get_all_logical_ports()
        lports2 = list()
        for lport in lports:
            lports2.append(lport.get_id())
        lports2.sort()
        self.assertEqual(ports2, lports2)

    def test_list_routers(self):
        routers = self.neutron.list_routers(retrieve_all=True)
        routers = routers['routers']
        routers1 = list()
        for router in routers:
            routers1.append(router['id'])
        routers1.sort()
        routers_in_db = self.nb_api.get_routers()
        routers2 = list()
        for router in routers_in_db:
            routers2.append(router.get_name())
        routers2.sort()
        self.assertEqual(routers1, routers2)
'''
