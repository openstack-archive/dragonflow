#!/usr/bin/env python
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from neutronclient.neutron import client
import os_client_config
import sys


def get_cloud_config(cloud='devstack-admin'):
    return os_client_config.OpenStackConfig().get_one_cloud(cloud=cloud)


def credentials(cloud='devstack-admin'):
    """Retrieves credentials to run functional tests"""
    return get_cloud_config(cloud=cloud).get_auth_args()


class Network(object):

    def __init__(self):
        creds = credentials()
        auth_url = creds['auth_url'] + "/v2.0"
        self.neutron = client.Client('2.0', username=creds['username'],
            password=creds['password'], auth_url=auth_url,
            tenant_name=creds['project_name'])

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

    def create_subnet_and_link_to_router(self, router_id, network_id, name,
        ip_net):
        subnet = {
            'cidr': ip_net,
            'name': name,
            'ip_version': 4,
            'network_id': network_id
        }
        subnet = self.neutron.create_subnet(body={'subnet': subnet})
        subnet_id = subnet['subnet']['id']
        try:
            self.neutron.add_interface_router(router_id, body={'subnet_id':
                subnet_id})
        except Exception as e:
            print(e)
            pass

    def create_subnet(self, router_id, network_id, name, ip_net):
        subnet = {
            'cidr': ip_net,
            'name': name,
            'ip_version': 4,
            'network_id': network_id
        }
        subnet = self.neutron.create_subnet(body={'subnet': subnet})

    def create_network(self, network_name, subnet):
        router_id = self.create_get_router('router1')
        network_id = self.create_get_net(network_name)
        self.create_subnet_and_link_to_router(router_id, network_id,
            network_name, subnet)

    def clean(self, network_name):
        networks = self.neutron.list_networks(name=network_name)['networks']
        for net in networks:
            print(net)
            ports = self.neutron.list_ports(network_id=net['id'])
            ports = ports['ports']
            for port in ports:
                print(port['device_owner'], port['id'])
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
                print(subnet)
                self.neutron.delete_subnet(subnet['id'])


def main():
    if len(sys.argv) == 3:
        test = Network()
        test.clean(sys.argv[1])
        test.create_network(sys.argv[1], sys.argv[2])
    else:
        sys.exit()

if __name__ == '__main__':
    sys.exit(main())
