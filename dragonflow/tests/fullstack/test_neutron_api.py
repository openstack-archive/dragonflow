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

from neutron.common import config as common_config
from neutron.tests import base
from neutronclient.neutron import client

from dragonflow.common import common_params
from dragonflow.db import api_nb
import test_objects as objects

cfg.CONF.register_opts(common_params.df_opts, 'df')


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
        self.neutron.add_interface_router(router_id, body=subnet_msg)
        router.delete()
        network.delete()
        self.assertFalse(router.exists())
        self.assertFalse(network.exists())
