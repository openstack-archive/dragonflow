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

from neutronclient.neutron import client
import os_client_config
import sys
import time


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)


def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()


class StressTest(object):

    def __init__(self):
        creds = credentials()
        tenant_name = creds['project_name']
        auth_url = creds['auth_url'] + "/v2.0"
        print creds
        self.neutron = client.Client('2.0', username=creds['username'],
             password=creds['password'], auth_url=auth_url,
             tenant_name=tenant_name)

    def create_get_router(self, name):
        routers = self.neutron.list_routers(name=name)
        routers = routers['routers']
        if len(routers) > 0:
            return routers[0]['id']
        router = {'name': name, 'admin_state_up': True}
        new_router = self.neutron.create_router({'router': router})
        self.router_id = new_router['router']['id']
        return self.router_id

    def create_get_net(self, name):
        networks = self.neutron.list_networks(name=name)['networks']
        networks_count = len(networks)
        if networks_count > 0:
            return networks[0]['id']
        network = {'name': name, 'admin_state_up': True, 'shared': False}
        network = self.neutron.create_network({'network': network})
        return network['network']['id']

    def create_subnet_and_link_to_router(self, router_id, net_id, name, cidr):
        subnet = {
            'cidr': cidr,
            'name': name,
            'ip_version': 4,
            'network_id': net_id
        }
        subnet = self.neutron.create_subnet(body={'subnet': subnet})
        subnet_id = subnet['subnet']['id']
        self.neutron.add_interface_router(router_id,
             body={'subnet_id': subnet_id})

    def create_subnet(self, network_id, name, ip_net):
        subnet = {
            'cidr': ip_net,
            'name': name,
            'ip_version': 4,
            'network_id': network_id
        }
        subnet = self.neutron.create_subnet(body={'subnet': subnet})

    def test1(self):
        nun_subnets = 0
        start = time.time()
        for j in range(1, 2):
            network_id = self.create_get_net('TEST-NETWORK-' + str(j))
            for i in range(255):
                cidr = '1.' + str(j) + '.' + str(i) + '.0/24'
                subnet_name = 'SUBNET-' + str(j) + '-' + str(i)
                self.create_subnet(network_id, subnet_name, cidr)
                nun_subnets = nun_subnets + 1
        end = time.time()
        total = end - start
        print("TEST1: time spend to create %d subnets: %d"
              % (nun_subnets, total))

    def test2(self):
        nun_subnets = 0
        router_id = self.create_get_router('TEST-ROUTER-1')
        for j in range(1, 2):
            network_id = self.create_get_net('TEST-NETWORK-' + str(j))
            start = time.time()
            for i in range(255):
                cidr = '1.' + str(j) + '.' + str(i) + '.0/24'
                subnet_name = 'TEST-SUBNET-' + str(j) + '-' + str(i)
                self.create_subnet_and_link_to_router(
                     router_id,
                     network_id,
                     subnet_name,
                     cidr)
                nun_subnets = nun_subnets + 1
        end = time.time()
        total = end - start
        print("TEST2: time spend to create %d subnets: %d"
              % (nun_subnets, total))

    def clean_network(self, name):
        print("Clean test results")
        networks = self.neutron.list_networks(name=name)['networks']
        for net in networks:
            ports = self.neutron.list_ports(network_id=net['id'])
            ports = ports['ports']
            for port in ports:
                if port['device_owner'] == 'network:router_interface':
                    for fip in port['fixed_ips']:
                        subnet_msg = {'subnet_id': fip['subnet_id']}
                        self.neutron.remove_interface_router(
                            port['device_id'], body=subnet_msg)
                elif port['device_owner'] == 'network:router_gateway':
                    pass
                else:
                    self.neutron.delete_port(port['id'])
            subnets = self.neutron.list_subnets(network_id=net['id'])
            subnets = subnets['subnets']
            for subnet in subnets:
                self.neutron.delete_subnet(subnet['id'])
            self.neutron.delete_network(net['id'])
        return


def main():
    test = StressTest()
    test.test1()
    test.clean_network('TEST-NETWORK-1')
    test.test2()
    test.clean_network('TEST-NETWORK-1')

if __name__ == '__main__':
    sys.exit(main())
