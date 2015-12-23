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
from oslo_serialization import jsonutils
from oslo_utils import importutils

from neutron.common import config as common_config
from neutron.tests import base
from neutronclient.neutron import client

from dragonflow.common import common_params
from dragonflow.db import api_nb

cfg.CONF.register_opts(common_params.df_opts, 'df')


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)


def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()


class RouterTestWrapper():

    def __init__(self, neutron, nb_api):
        self.router_id = ""
        self.neutron = neutron
        self.nb_api = nb_api
        self.deleted = False

    def create(self):
        router = {'name': 'myrouter1', 'admin_state_up': True}
        new_router = self.neutron.create_router({'router': router})
        self.router_id = new_router['router']['id']
        return self.router_id

    def __del__(self):
        print("in delete")
        if self.deleted or len(self.router_id) == 0:
            return
        print("in delete2")
        self.delete()

    def delete(self):
        #router = self.neutron.show_router(router_id)
        ports = self.neutron.list_ports(device_id=self.router_id)
        ports = ports['ports']
        for port in ports:
            self.neutron.delete_port(port['id'])
        self.neutron.delete_router( self.router_id )
        self.deleted = True

    def check(self):
        routers = self.nb_api.get_routers()
        for router in routers:
            if router.get_name() == self.router_id:
                return True
        return False

class NetworkTestWrapper():

    def __init__(self, neutron, nb_api):
        self.network_id = ""
        self.neutron = neutron
        self.nb_api = nb_api
        self.deleted = False

    def create(self):
        network = {'name': 'mynetwork1', 'admin_state_up': True}
        network = self.neutron.create_network({'network': network})
        self.network_id = network['network']['id']
        return self.network_id

    def __del__(self):
        if self.deleted or len(self.network_id) == 0:
            return
        self.delete()

    def delete(self):
        subnets = self.neutron.list_subnets(device_id=self.network_id)
        subnets = subnets['subnets']
        #for subnet in subnets:
        #print("delete sub-network", subnet['id'], subnet)
        #self.neutron.delete_subnet( subnet['id'] )
        self.neutron.delete_network( self.network_id )
        self.deleted = True

    def check(self):
        network = self.nb_api.get_lswitch(self.network_id)
        if network:
            return True
        return False


class TestNeutronAPIandDB(base.BaseTestCase):

    def setUp(self):
        super(TestNeutronAPIandDB, self).setUp()
        creds = credentials()
        tenant_name = creds['project_name']
        auth_url = creds['auth_url'] #+ "/v2.0"
        self.neutron = client.Client('2.0', username=creds['username'],
             password=creds['password'], auth_url=auth_url,
             tenant_name=tenant_name)
        self.neutron.format = 'json'
        common_config.init(['--config-file', '/etc/neutron/neutron.conf'])

        db_driver_class = importutils.import_class(cfg.CONF.df.nb_db_class)
        self.nb_api = api_nb.NbApi(db_driver_class())
        self.nb_api.initialize(db_ip=cfg.CONF.df.remote_db_ip,
            db_port=cfg.CONF.df.remote_db_port)
        self.test_router_name = 'myrouter1'
        self.test_network_name = 'mynetwork1'
        #self.clean_all()

    def clean_all(self):
        #routers = self.neutron.list_routers(retrieve_all=True)
        routers = self.neutron.list_routers(name=self.test_router_name)
        routers = routers['routers']
        #routers = jsonutils.loads(routers)
        for router in routers:
            ports = self.neutron.list_ports(device_id=router['id'])
            ports = ports['ports']
            for port in ports:
                self.neutron.delete_port(port['id'])
            self.neutron.delete_router(router['id'])
        networks = self.neutron.list_networks(name=self.test_network_name)
        networks = networks['networks']
        for network in networks:
            for subnet in network['subnets']:
                self.neutron.delete_subnet( subnet )
            #if network['subnets'] and len(network['subnets']) > 0:
            self.neutron.delete_network( network['id'] )

    def test_create_network(self):
        network = NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        network_found = network.check()
        self.assertTrue( network_found )
        network.delete()
        network_found = network.check()
        self.assertFalse( network_found )

    def test_dhcp_port_created(self):
        network = NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        network_found = network.check()
        self.assertTrue( network_found )
        subnet = {'network_id': network_id,
            'cidr': '10.1.0.0/24',
            'gateway_ip': '10.1.0.1',
            'ip_version': 4,
            'name': 'subnet-test',
            'enable_dhcp': True}
        subnets = self.neutron.create_subnet({'subnet': subnet})
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
        router = RouterTestWrapper( self.neutron, self.nb_api)
        router_id = router.create()
        router_found = router.check()
        self.assertTrue( router_found )
        router.delete()
        router_found = router.check()
        self.assertFalse(router_found)

    def test_create_router_interface(self):
        router = RouterTestWrapper( self.neutron, self.nb_api)
        network = NetworkTestWrapper(self.neutron, self.nb_api)
        network_id = network.create()
        network_found = network.check()
        self.assertTrue( network_found )
        subnet = {'subnets': [{'cidr': '192.168.199.0/24',
                  'ip_version': 4, 'network_id': network_id}]}
        subnets = self.neutron.create_subnet(body=subnet)
        subnet = subnets['subnets'][0]
        router_id = router.create()
        router_found = router.check()
        self.assertTrue( router_found )
        subnet_msg = {'subnet_id': subnet['id']}
        port = self.neutron.add_interface_router( router_id, body=subnet_msg)
        router.delete()
        network.delete()
        #self.neutron.delete_port( port['port_id'] )
        #self.neutron.delete_router( router_id )
        #self.neutron.delete_subnet( subnet['id'] )
        #self.neutron.delete_network( network_id )
        router_found = router.check()
        self.assertFalse(router_found)
        network_found = network.check()
        self.assertFalse(network_found)
